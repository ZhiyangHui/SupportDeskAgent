"""真实数据库验证接管权限、人工消息幂等及模型暂停；测试事务结束全部回滚。"""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.agent.schemas import SupportIntent, TicketPriority
from app.agent.tools import SupportToolContext
from app.core.access import customer_identity, require_staff
from app.core.config import get_settings
from app.db.models import (
    Company,
    Conversation,
    CustomerAccount,
    Message,
    MessageRole,
    StaffAccount,
)
from app.db.session import get_db_session
from app.main import create_app
from app.schema.access import Principal
from app.services.agent_memory_service import conversation_config, run_graph_turn


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("SUPPORT_TEST_DATABASE") != "1", reason="需要本地 PostgreSQL")
async def test_handoff_api_permissions_and_pause(monkeypatch):
    settings = get_settings()
    assert "127.0.0.1" in settings.database_url or "localhost" in settings.database_url
    model = AsyncMock(side_effect=AssertionError("人工接管期间不得调用模型"))
    monkeypatch.setattr("app.services.conversation_service.run_graph_turn", model)
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
                    suffix = uuid4().hex
                    company = Company(code=suffix, name="接管测试企业")
                    customer = CustomerAccount(username=suffix, display_name="客户", password_hash="unused")
                    session.add_all([company, customer])
                    await session.flush()
                    staff = StaffAccount(company_id=company.id, username=suffix, display_name="客服小李", password_hash="unused")
                    session.add(staff)
                    await session.flush()
                    conversation = Conversation(customer_id=customer.id, company_id=company.id)
                    session.add(conversation)
                    await session.commit()
                    cid = conversation.id
                    employee = Principal(id=staff.id, company_id=company.id, audience="staff", display_name=staff.display_name)
                    client_identity = Principal(id=customer.id, audience="customer", display_name="客户")
                    app = create_app()

                    async def database():
                        yield session

                    app.dependency_overrides[get_db_session] = database
                    app.dependency_overrides[require_staff] = lambda: employee
                    app.dependency_overrides[customer_identity] = lambda: client_identity
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                        base = f"/api/v1/staff/conversations/{cid}"
                        reply = {"content": "您好，我来协助处理。", "client_request_id": str(uuid4())}
                        assert (await client.get("/api/v1/staff/handoffs")).json()["total"] == 0
                        # 用明确的图结果验证真实 Service 将转人工状态与回复一起落库，而不是前端猜测文案。
                        monkeypatch.setattr("app.services.conversation_service.get_support_graph", lambda: object())
                        model.side_effect = None
                        model.return_value = {"final_reply": "已提交人工请求", "requires_human": True,
                            "intent": SupportIntent.GENERAL, "priority": TicketPriority.MEDIUM, "decision_reason": "客户主动申请人工客服"}
                        request = {"company_id": str(company.id), "conversation_id": str(cid), "message": "转人工", "client_request_id": str(uuid4())}
                        queued = await client.post("/api/v1/agent/chat", json=request)
                        assert queued.status_code == 200, queued.text
                        queue = (await client.get("/api/v1/staff/handoffs")).json()
                        assert queue["total"] == 1 and queue["items"][0]["conversation_id"] == str(cid)
                        assert queue["items"][0]["reason"] == "客户主动申请人工客服"
                        assert (await client.get("/api/v1/staff/handoffs?offset=1&limit=1")).json()["items"] == []
                        model.reset_mock()
                        model.side_effect = AssertionError("人工接管期间不得调用模型")
                        assert (await client.post(base + "/reply", json=reply)).status_code == 409
                        response = await client.post(base + "/handoff", json={"action": "takeover"})
                        assert response.status_code == 200, response.text
                        assert response.json()["status"] == "handed_off"
                        assert (await client.get("/api/v1/staff/handoffs")).json()["total"] == 0
                        assert (await client.get("/api/v1/staff/handoffs?scope=mine")).json()["total"] == 1
                        assert (await client.get(f"/api/v1/customer/conversations/{cid}/handoff")).json()["status"] == "handed_off"
                        data = {"company_id": str(company.id), "conversation_id": str(cid), "message": "请人工帮忙", "client_request_id": str(uuid4())}
                        sent = await client.post("/api/v1/agent/chat", json=data)
                        assert sent.status_code == 200, sent.text
                        assert sent.json()["delivery_mode"] == "human"
                        assert sent.json()["agent_message_id"] is None
                        assert (await client.post("/api/v1/agent/chat", json=data)).json() == sent.json()
                        model.assert_not_awaited()
                        first = await client.post(base + "/reply", json=reply)
                        second = await client.post(base + "/reply", json=reply)
                        assert first.status_code == 200 and first.json() == second.json()
                        assert first.json()["role"] == "staff"
                        assert await session.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == cid)) == 4
                        assert (await client.post(base + "/reply", json={**reply, "content": "不同内容"})).status_code == 409
                        history = await client.get(f"/api/v1/conversations/{cid}/messages")
                        assert [item["role"] for item in history.json()] == ["customer", "agent", "customer", "staff"]
                        # 同企业其他员工不能抢走会话；其他企业连会话都不能读。
                        app.dependency_overrides[require_staff] = lambda: employee.model_copy(update={"id": uuid4()})
                        assert (await client.post(base + "/handoff", json={"action": "resume"})).status_code == 409
                        app.dependency_overrides[require_staff] = lambda: employee.model_copy(update={"company_id": uuid4()})
                        assert (await client.get("/api/v1/staff/handoffs?scope=mine")).json()["total"] == 0
                        assert (await client.get(base + "/handoff")).status_code == 404
                        app.dependency_overrides[customer_identity] = lambda: client_identity.model_copy(update={"id": uuid4()})
                        assert (await client.get(f"/api/v1/customer/conversations/{cid}/handoff")).status_code == 404
                        app.dependency_overrides[require_staff] = lambda: employee
                        resumed = await client.post(base + "/handoff", json={"action": "resume"})
                        assert resumed.json()["status"] == "active"
                        assert resumed.json()["handoff_requested_at"] is None
                        assert (await client.get("/api/v1/staff/handoffs")).json()["total"] == 0
                        assert (await client.get("/api/v1/staff/handoffs?scope=mine")).json()["total"] == 0
                        await session.refresh(conversation)
                        assert conversation.memory_generation == 1
                        assert (await client.post(base + "/reply", json={**reply, "client_request_id": str(uuid4())})).status_code == 409
                        assert await session.scalar(select(func.count()).select_from(Message).where(Message.role == MessageRole.STAFF, Message.conversation_id == cid)) == 1
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_resume_imports_human_history_into_new_checkpoint():
    # 原检查点代次保持不变；新代次首次导入人工期间的历史，而非继续旧工作流。
    customer, company, conversation = uuid4(), uuid4(), uuid4()
    original = SupportToolContext(AsyncMock(), conversation, customer, company)
    resumed = SupportToolContext(AsyncMock(), conversation, customer, company, memory_generation=1)
    assert conversation_config(original) != conversation_config(resumed)
    graph = SimpleNamespace(checkpointer=object(), aget_state=AsyncMock(return_value=SimpleNamespace(next=(), values={})), ainvoke=AsyncMock(return_value={"final_reply": "收到"}))
    history = [Message(id=uuid4(), role=MessageRole.CUSTOMER, content="请人工处理"), Message(id=uuid4(), role=MessageRole.STAFF, content="客服：已为您核实"), Message(id=uuid4(), role=MessageRole.CUSTOMER, content="后续怎么办")]
    await run_graph_turn(graph, history, history[-1], resumed)
    inputs = graph.ainvoke.call_args.args[0]
    assert [item.content for item in inputs["messages"]] == [item.content for item in history]
    assert inputs["order_memory"].stage == "idle"
    assert graph.ainvoke.call_args.kwargs["config"] == conversation_config(resumed)
