"""真实 PostgreSQL + API + ToolNode 闭环；外层事务回滚所有业务测试数据。"""

import os
from unittest.mock import AsyncMock
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.agent.graph import build_support_graph
from app.core.access import customer_identity
from app.core.config import get_settings
from app.db.chat_operation import ChatOperation
from app.db.conversation_repository import ConversationRepository
from app.db.customer_repository import CustomerRepository
from app.db.models import (
    Company,
    CustomerAccount,
    MessageRole,
    Ticket,
    TicketActivity,
    TicketPriorityValue,
    TicketSource,
    TicketStatus,
)
from app.db.session import get_db_session
from app.main import create_app
from app.schema.access import Principal
from app.schema.ticket_edit import TicketChanges, TicketEditInput
from app.services.ticket_edit_service import TicketEditService
from app.services.ticket_service import TicketService
from tests.test_ticket_edit import edit_decision


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("SUPPORT_TEST_DATABASE") != "1", reason="需要本地数据库及最新迁移"
)
async def test_edit_api_idempotency_permissions_and_committed_failure(monkeypatch):
    settings = get_settings()
    assert "127.0.0.1" in settings.database_url or "localhost" in settings.database_url
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    suffix = uuid4().hex
                    company = Company(code="comment-" + suffix, name="补充测试企业")
                    other_company = Company(code="foreign-" + suffix, name="其他企业")
                    customer = CustomerAccount(
                        username="comment-" + suffix,
                        display_name="客户",
                        password_hash="not-used",
                    )
                    stranger = CustomerAccount(
                        username="stranger-" + suffix,
                        display_name="他人",
                        password_hash="not-used",
                    )
                    session.add_all([company, other_company, customer, stranger])
                    await session.flush()
                    company_id, other_company_id, customer_id, stranger_id = (
                        company.id,
                        other_company.id,
                        customer.id,
                        stranger.id,
                    )
                    conversation = await ConversationRepository(
                        session
                    ).create_conversation()
                    conversation.company_id, conversation.customer_id = (
                        company_id,
                        customer_id,
                    )
                    conversation_id = conversation.id
                    tickets = []
                    for owner, enterprise, status in [
                        (customer_id, company_id, TicketStatus.OPEN),
                        (stranger_id, company_id, TicketStatus.OPEN),
                        (customer_id, other_company_id, TicketStatus.OPEN),
                        (customer_id, company_id, TicketStatus.CLOSED),
                    ]:
                        ticket = Ticket(
                            code="TK-" + uuid4().hex[:20],
                            customer_id=owner,
                            company_id=enterprise,
                            title="设备维修",
                            description="原始描述",
                            category="technical",
                            priority=TicketPriorityValue.MEDIUM,
                            source=TicketSource.MANUAL,
                            status=status,
                        )
                        session.add(ticket)
                        tickets.append(ticket)
                    await session.commit()
                    ticket_ids, codes = (
                        [item.id for item in tickets],
                        [item.code for item in tickets],
                    )
                    model = AsyncMock()
                    model.ainvoke.return_value = edit_decision(
                        action="new", reference=codes[0], description="设备开机会冒烟"
                    )
                    graph = build_support_graph(model, checkpointer=InMemorySaver())
                    monkeypatch.setattr(
                        "app.services.conversation_service.get_support_graph",
                        lambda: graph,
                    )
                    app = create_app()

                    async def db():
                        yield session

                    app.dependency_overrides[get_db_session] = db
                    app.dependency_overrides[customer_identity] = lambda: Principal(
                        id=customer_id, audience="customer", display_name="客户"
                    )
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app), base_url="http://test"
                    ) as client:
                        request = {
                            "message": f"给工单 {codes[0]} 补充：设备开机会冒烟",
                            "company_id": str(company_id),
                            "conversation_id": str(conversation_id),
                            "client_request_id": str(uuid4()),
                        }
                        # 首轮即使给出完整编号和修改内容，也必须先选中候选，再确认预览。
                        first = await client.post("/api/v1/agent/chat", json=request)
                        assert "请选择" in first.json()["reply"]
                        selected = await client.post(
                            "/api/v1/agent/chat",
                            json={
                                **request,
                                "message": "1",
                                "client_request_id": str(uuid4()),
                            },
                        )
                        assert "拟修改内容" in selected.json()["reply"]
                        request = {
                            **request,
                            "message": "确认修改",
                            "client_request_id": str(uuid4()),
                        }
                        response = await client.post("/api/v1/agent/chat", json=request)
                        assert response.status_code == 200, response.text
                        data = response.json()
                        assert data["executed_tool"] == "update_support_ticket"
                        assert data["updated_ticket_code"] == codes[0]
                        assert data["created_ticket_code"] is None
                        assert (
                            await client.post("/api/v1/agent/chat", json=request)
                        ).json() == data
                        model.ainvoke.assert_awaited_once()
                        operation_id = uuid5(
                            NAMESPACE_URL,
                            f"supportdesk:{customer_id}:{company_id}:{request['client_request_id']}",
                        )
                        # 即使绕过 HTTP 重放到 Tool 服务，同键也返回原活动，不重复写入。
                        await TicketEditService(session).update(
                            conversation_id,
                            operation_id,
                            TicketEditInput(
                                ticket_code=codes[0],
                                expected_version=1,
                                changes=TicketChanges(description="设备开机会冒烟"),
                            ),
                        )
                        count = await session.scalar(
                            select(func.count())
                            .select_from(TicketActivity)
                            .where(TicketActivity.ticket_id == ticket_ids[0])
                        )
                        assert count == 1
                        stored = await session.get(
                            Ticket, ticket_ids[0], populate_existing=True
                        )
                        assert (
                            stored.description == "设备开机会冒烟"
                            and stored.version == 2
                        )
                        # 企业详情时间线可见，但内部备注必须从客户查询结果中过滤掉。
                        staff_view = await TicketService(
                            session, company_id
                        ).get_ticket(ticket_ids[0])
                        assert "修改前：原始描述" in staff_view.activities[0].content
                        assert (
                            "修改后：设备开机会冒烟" in staff_view.activities[0].content
                        )
                        await TicketService(session, company_id).add_note(
                            ticket_ids[0],
                            content="内部核验信息，不向客户开放",
                            operator_name="企业客服",
                        )
                        comments_url = (
                            f"/api/v1/customer/tickets/{ticket_ids[0]}/comments"
                        )
                        comments = (await client.get(comments_url)).json()
                        assert (
                            len(comments) == 1
                            and "修改后：设备开机会冒烟" in comments[0]["content"]
                        )
                        assert (
                            await client.get(
                                f"/api/v1/customer/tickets/{ticket_ids[1]}/comments"
                            )
                        ).status_code == 404
                        history = (
                            await client.get(
                                f"/api/v1/conversations/{conversation_id}/messages"
                            )
                        ).json()
                        assert (
                            history[-1]["tool_call"]["name"] == "update_support_ticket"
                        )
                        # 预览版本过期时写服务必须拒绝，不能只依赖 Graph 的前置检查。
                        stale_op = ChatOperation(
                            id=uuid4(),
                            customer_id=customer_id,
                            company_id=company_id,
                            fingerprint="stale",
                        )
                        session.add(stale_op)
                        await session.commit()
                        stale = await TicketEditService(session).update(
                            conversation_id,
                            stale_op.id,
                            TicketEditInput(
                                ticket_code=codes[0],
                                expected_version=1,
                                changes=TicketChanges(title="过期修改"),
                            ),
                        )
                        assert not stale.success and stale.conflict
                        # 写入已提交、保存 AI 回复时失败：回执必须明确是补充成功，而非创建成功。
                        model.ainvoke.return_value = edit_decision(
                            action="new", reference=codes[0], desired_resolution="维修"
                        )
                        next_request = {
                            **request,
                            "message": "把诉求改成维修",
                            "client_request_id": str(uuid4()),
                        }
                        first = await client.post(
                            "/api/v1/agent/chat", json=next_request
                        )
                        assert "请选择" in first.json()["reply"]
                        selected = await client.post(
                            "/api/v1/agent/chat",
                            json={
                                **request,
                                "message": "1",
                                "client_request_id": str(uuid4()),
                            },
                        )
                        assert "拟修改内容" in selected.json()["reply"]
                        original_add = ConversationRepository.add_message

                        async def fail_reply(
                            self, conversation_id, role, content, **kwargs
                        ):
                            if role == MessageRole.AGENT:
                                raise RuntimeError("模拟写入后回复失败")
                            return await original_add(
                                self, conversation_id, role, content, **kwargs
                            )

                        monkeypatch.setattr(
                            ConversationRepository, "add_message", fail_reply
                        )
                        failed_request = {**request, "client_request_id": str(uuid4())}
                        failed = await client.post(
                            "/api/v1/agent/chat", json=failed_request
                        )
                        assert failed.status_code == 502, failed.text
                        assert failed.json()["detail"]["outcome"] == "ticket_updated"
                        assert "已修改" in failed.json()["detail"]["message"]
                        again = await client.post(
                            "/api/v1/agent/chat", json=failed_request
                        )
                        assert again.json()["detail"]["outcome"] == "ticket_updated"
                        assert len((await client.get(comments_url)).json()) == 2
                    # 写服务自身再次鉴权，模型即使指定他人或另一企业编号也无法写入。
                    for code in codes[1:]:
                        op = ChatOperation(
                            id=uuid4(),
                            customer_id=customer_id,
                            company_id=company_id,
                            fingerprint="test",
                        )
                        session.add(op)
                        await session.commit()
                        op_id = op.id
                        result = await TicketEditService(session).update(
                            conversation_id,
                            op_id,
                            TicketEditInput(
                                ticket_code=code,
                                expected_version=1,
                                changes=TicketChanges(description="越权或已关闭测试"),
                            ),
                        )
                        assert not result.success
                    assert (
                        await CustomerRepository(session).list_comments(
                            stranger_id, ticket_ids[0], 0, 20
                        )
                        is None
                    )
                    foreign_count = await session.scalar(
                        select(func.count())
                        .select_from(TicketActivity)
                        .where(TicketActivity.ticket_id.in_(ticket_ids[1:]))
                    )
                    assert foreign_count == 0
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()
