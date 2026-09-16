"""真实数据库模拟订单闭环，外层事务回滚全部测试数据，不调用付费模型。"""

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.agent.graph import build_support_graph
from app.agent.schemas import AgentDecision
from app.agent.tools import SupportToolContext
from app.core.access import customer_identity
from app.core.config import get_settings
from app.db.models import Company, CustomerAccount, Message, Ticket
from app.db.order_repository import OrderRepository
from app.db.session import get_db_session
from app.main import create_app
from app.schema.access import Principal
from app.schema.order import OrderPage, OrderResponse, OrderSearch
from app.services.order_service import OrderService


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_tool_call", [False, True])
async def test_multiple_matching_orders_cannot_be_chosen_arbitrarily(monkeypatch, missing_tool_call):
    """即使模型想直接选择第一单，多个匹配仍必须先由客户消歧。"""
    monkeypatch.setattr(
        "app.agent.tools.ConversationRepository.get_conversation",
        AsyncMock(
            return_value=SimpleNamespace(
                id=uuid4(), customer_id=uuid4(), company_id=uuid4()
            )
        ),
    )
    page = OrderPage(
        items=[
            OrderResponse(
                id=uuid4(),
                code=f"MO-{i}",
                product_name="机械设备",
                amount="99.00",
                status="paid",
                created_at=datetime.now(UTC),
            )
            for i in range(2)
        ],
        total=2,
    )
    monkeypatch.setattr(
        "app.agent.tools.OrderService.list", AsyncMock(return_value=page)
    )
    writer = AsyncMock()
    monkeypatch.setattr("app.agent.tools.TicketService.create_ticket", writer)
    decider = AsyncMock()
    decider.ainvoke.return_value = AgentDecision(
        intent="order",
        priority="medium",
        requires_human=False,
        should_create_ticket=True,
        needs_ticket_details=False,
        needs_order_lookup=True,
        ticket_title="机械故障",
        ticket_description="希望退款",
        reason="客户要求建单",
        reply="先查订单",
    )
    # 不论旧工具模型准备直接回复还是擅自建单，新流程都不让它决定候选选择。
    order_llm = AsyncMock()
    order_llm.ainvoke.return_value = AIMessage(content="请补充信息") if missing_tool_call else AIMessage(
        content="", tool_calls=[{"name": "create_order_ticket", "id": "unsafe", "args": {"order_id": str(page.items[0].id), "issue": "退款"}}],
    )
    result = await build_support_graph(decider, order_llm=order_llm).ainvoke(
        {"messages": []}, context=SupportToolContext(AsyncMock(), uuid4())
    )
    assert "找到多笔订单" in result["final_reply"]
    assert result["order_rounds"] == 1
    assert "MO-0" in result["final_reply"] and "MO-1" in result["final_reply"]
    writer.assert_not_awaited()
    order_llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("SUPPORT_TEST_DATABASE") != "1", reason="需要本地数据库")
@pytest.mark.parametrize("selected_number", ["1", "2"])
async def test_demo_orders_and_agent_ticket(monkeypatch, selected_number):
    settings = get_settings()
    assert "localhost" in settings.database_url or "127.0.0.1" in settings.database_url
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    engine = create_async_engine(settings.database_url)
    app = create_app()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    suffix = uuid4().hex
                    company = Company(code="orders-" + suffix, name="测试企业")
                    other_company = Company(code="other-" + suffix, name="其他企业")
                    customer = CustomerAccount(
                        username="orders-" + suffix,
                        display_name="测试客户",
                        password_hash="not-used",
                    )
                    stranger = CustomerAccount(
                        username="other-" + suffix,
                        display_name="其他客户",
                        password_hash="not-used",
                    )
                    session.add_all([company, other_company, customer, stranger])
                    await session.commit()

                    async def db():
                        yield session

                    app.dependency_overrides[get_db_session] = db
                    app.dependency_overrides[customer_identity] = lambda: Principal(
                        id=customer.id, audience="customer", display_name="测试客户"
                    )
                    path = f"/api/v1/customer/companies/{company.id}/orders"
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app), base_url="http://test"
                    ) as client:
                        initial = await client.get(path)
                        assert initial.status_code == 200, initial.text
                        assert initial.json()["total"] == 3
                        assert (await client.get(path)).json()["total"] == 3
                        body = {
                            "product_name": "测试打印机",
                            "amount": "123.45",
                            "status": "paid",
                            "client_request_id": str(uuid4()),
                        }
                        created = await client.post(path, json=body)
                        assert created.status_code == 201, created.text
                        assert (await client.post(path, json=body)).json()[
                            "id"
                        ] == created.json()["id"]
                        assert (await client.get(path)).json()["total"] == 4
                        assert (
                            await client.post(path, json={**body, "amount": "-1"})
                        ).status_code == 422
                        assert (
                            await client.post(
                                path, json={**body, "product_name": "另一个商品"}
                            )
                        ).status_code == 409
                        # 同一测试 Session 经错误回滚后 ORM 属性会过期，显式刷新而非触发同步懒加载。
                        for identity in (customer, stranger, company, other_company):
                            await session.refresh(identity)
                        foreign = await OrderService(
                            session, stranger.id, company.id
                        ).list(OrderSearch())
                        other = await OrderService(
                            session, customer.id, other_company.id
                        ).list(OrderSearch())
                        assert foreign.total == other.total == 3
                        assert (
                            await OrderRepository(session, customer.id, company.id).get(
                                foreign.items[0].id
                            )
                            is None
                        )
                        assert (
                            await OrderRepository(session, customer.id, company.id).get(
                                other.items[0].id
                            )
                            is None
                        )
                        llm = AsyncMock()
                        llm.ainvoke.return_value = AgentDecision(
                            intent="order",
                            priority="medium",
                            requires_human=False,
                            should_create_ticket=True,
                            needs_ticket_details=False,
                            needs_order_lookup=True,
                            ticket_title="机械故障退款",
                            ticket_description="机械故障，希望退款",
                            ticket_category="order",
                            reason="请求关联订单建单",
                            reply="查询订单",
                        )
                        selection_decider = AsyncMock()
                        selection_decider.ainvoke.return_value = llm.ainvoke.return_value.model_copy(update={
                            "should_create_ticket": False, "needs_ticket_details": True,
                        })
                        graph = build_support_graph(selection_decider, checkpointer=InMemorySaver())
                        monkeypatch.setattr(
                            "app.services.conversation_service.get_support_graph",
                            lambda: graph,
                        )
                        # 两次独立 API 请求验证数据库状态恢复，不能只在同一 Graph 内测状态。
                        selection = await client.post("/api/v1/agent/chat", json={
                            "message": "请帮我创建一个订单售后工单",
                            "company_id": str(company.id), "client_request_id": str(uuid4()),
                        })
                        assert selection.status_code == 200, selection.text
                        assert selection.json()["created_ticket_id"] is None
                        from uuid import UUID
                        config = {"configurable": {"thread_id": f"{company.id}:{customer.id}:{selection.json()['conversation_id']}"}}

                        message = await session.get(Message, UUID(selection.json()["agent_message_id"]))
                        memory = (await graph.aget_state(config)).values["order_memory"]
                        assert "order_memory" not in (message.tool_payload or {})
                        assert memory.stage == "select_order"
                        target = memory.candidates[int(selected_number) - 1]
                        # 客户实际看到的顺序必须与持久化候选一致，不经过模型重新排序。
                        assert f"{selected_number}. {target.product_name}（{target.code}）" in selection.json()["reply"]
                        invalid = await client.post("/api/v1/agent/chat", json={
                            "message": "99", "conversation_id": selection.json()["conversation_id"],
                            "company_id": str(company.id), "client_request_id": str(uuid4()),
                        })
                        assert "序号不在" in invalid.json()["reply"]
                        chosen = await client.post("/api/v1/agent/chat", json={
                            "message": selected_number, "conversation_id": selection.json()["conversation_id"],
                            "company_id": str(company.id), "client_request_id": str(uuid4()),
                        })
                        assert chosen.status_code == 200, chosen.text
                        message = await session.get(Message, UUID(chosen.json()["agent_message_id"]))
                        memory = (await graph.aget_state(config)).values["order_memory"]
                        assert "order_memory" not in (message.tool_payload or {})
                        assert memory.stage == "collect_issue" and memory.selected == target
                        chat_body = {
                            "message": "维修",
                            "conversation_id": selection.json()["conversation_id"],
                            "company_id": str(company.id),
                            "client_request_id": str(uuid4()),
                        }
                        reply = await client.post("/api/v1/agent/chat", json=chat_body)
                        assert reply.status_code == 200, reply.text
                        ticket = await session.get(
                            Ticket, UUID(reply.json()["created_ticket_id"])
                        )
                        assert ticket and ticket.order_id
                        assert (
                            "维修" in ticket.description
                            and target.code in ticket.description
                        )
                        message = await session.get(Message, UUID(reply.json()["agent_message_id"]))
                        memory = (await graph.aget_state(config)).values["order_memory"]
                        assert "order_memory" not in (message.tool_payload or {})
                        assert memory.stage == "completed" and memory.selected is None
                        assert reply.json()["executed_tool"] == "create_order_ticket"
                        assert (
                            await client.post("/api/v1/agent/chat", json=chat_body)
                        ).json() == reply.json()
                        # 完成后新请求重新展示候选；取消准备只清理状态，不撤销已创建工单。
                        restarted = await client.post("/api/v1/agent/chat", json={
                            "message": "请帮我创建一个订单售后工单",
                            "conversation_id": selection.json()["conversation_id"],
                            "company_id": str(company.id), "client_request_id": str(uuid4()),
                        })
                        assert restarted.json()["created_ticket_id"] is None
                        assert "找到多笔订单" in restarted.json()["reply"]
                        cancelled = await client.post("/api/v1/agent/chat", json={
                            "message": "取消建单", "conversation_id": selection.json()["conversation_id"],
                            "company_id": str(company.id), "client_request_id": str(uuid4()),
                        })
                        assert cancelled.status_code == 200 and cancelled.json()["created_ticket_id"] is None
                        message = await session.get(Message, UUID(cancelled.json()["agent_message_id"]))
                        memory = (await graph.aget_state(config)).values["order_memory"]
                        assert "order_memory" not in (message.tool_payload or {})
                        assert memory.stage == "cancelled" and memory.selected is None
                        # 序号、明确的短诉求和取消无需再由模型猜测，整条链路不消耗模型调用。
                        selection_decider.ainvoke.assert_not_awaited()
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
