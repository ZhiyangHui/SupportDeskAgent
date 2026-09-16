"""真实数据库的双账号、双企业、双客户闭环，所有测试写入由外层事务回滚。"""

import os
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.agent.graph import DecisionLLM, ToolCallingLLM, build_support_graph
from app.agent.schemas import (
    AgentDecision,
    SupportIntent,
    TicketCategory,
    TicketPriority,
)
from app.core.access import CUSTOMER_COOKIE, STAFF_COOKIE
from app.core.config import get_settings
from app.db.auth_repository import AuthRepository
from app.db.chat_operation import ChatOperation
from app.db.conversation_repository import ConversationRepository
from app.db.identity_models import LoginSession
from app.db.models import MessageRole
from app.db.session import get_db_session
from app.main import create_app
from app.schema.ticket_query import TicketQueryInput
from app.services.auth_service import token_digest
from app.services.ticket_query_service import TicketQueryService
from tests.test_agent_graph import StubDecisionLLM, StubTicketCreationLLM
from tests.test_ticket_query import StubTicketQueryLLM, query_graph


@pytest.mark.asyncio
@pytest.mark.parametrize("category", [TicketCategory.ACCOUNT, TicketCategory.ORDER])
@pytest.mark.skipif(
    os.getenv("SUPPORT_TEST_DATABASE") != "1", reason="显式启用本地数据库集成测试"
)
async def test_dual_auth_multitenant_ticket_flow(monkeypatch, category):
    settings = get_settings()
    assert "127.0.0.1" in settings.database_url or "localhost" in settings.database_url
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    decision = AgentDecision(
        intent=SupportIntent.TICKET,
        priority=TicketPriority.HIGH,
        requires_human=True,
        should_create_ticket=True,
        needs_ticket_details=False,
        ticket_title="企业账号无法登录",
        ticket_description="企业控制台提示账号被锁定，需要协助核验。",
        ticket_category=category,
        reason="客户要求建单",
        reply="正在创建工单",
    )
    graph = build_support_graph(
        cast(DecisionLLM, StubDecisionLLM(decision)),
        cast(ToolCallingLLM, StubTicketCreationLLM()),
        checkpointer=InMemorySaver(),
    )
    monkeypatch.setattr(
        "app.services.conversation_service.get_support_graph", lambda: graph
    )
    app = create_app()
    engine = create_async_engine(settings.database_url)
    suffix = uuid4().hex[:10]
    password = "12345678"
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:

                    async def override_session():
                        yield session

                    app.dependency_overrides[get_db_session] = override_session
                    transport = httpx.ASGITransport(
                        app=app, client=("isolated-" + suffix, 1234)
                    )
                    async with (
                        httpx.AsyncClient(
                            transport=transport, base_url="http://test"
                        ) as customer,
                        httpx.AsyncClient(
                            transport=transport, base_url="http://test"
                        ) as stranger,
                        httpx.AsyncClient(
                            transport=transport, base_url="http://test"
                        ) as staff_a,
                        httpx.AsyncClient(
                            transport=transport, base_url="http://test"
                        ) as staff_b,
                    ):
                        company_ids = []
                        for code, client in (
                            ("alpha-" + suffix, staff_a),
                            ("beta-" + suffix, staff_b),
                        ):
                            body = {
                                "company_code": code,
                                "company_name": code,
                                "username": "agent",
                                "password": password,
                                "display_name": "企业客服",
                            }
                            registered = await client.post(
                                "/api/v1/access/staff/register-company", json=body
                            )
                            assert registered.status_code == 201, registered.text
                            assert (
                                await client.post(
                                    "/api/v1/access/staff/register-company", json=body
                                )
                            ).status_code == 409
                            login = await client.post(
                                "/api/v1/access/staff/login",
                                json={
                                    "company_code": code,
                                    "username": "agent",
                                    "password": password,
                                },
                            )
                            assert login.status_code == 200, login.text
                            company_ids.append(login.json()["company_id"])
                            assert (
                                await client.get("/api/v1/access/customer")
                            ).status_code == 401
                        for username, client in (
                            ("customer-" + suffix, customer),
                            ("other-" + suffix, stranger),
                        ):
                            assert (
                                await client.post(
                                    "/api/v1/access/customer/register",
                                    json={
                                        "username": username,
                                        "password": password,
                                        "display_name": username,
                                    },
                                )
                            ).status_code == 201
                            assert (
                                await client.post(
                                    "/api/v1/access/customer/login",
                                    json={"username": username, "password": password},
                                )
                            ).status_code == 200
                            assert (
                                await client.get("/api/v1/access/staff")
                            ).status_code == 401
                        # 凭证即使改名复制，也不能跨 audience 使用。
                        staff_token = staff_a.cookies.get(STAFF_COOKIE)
                        forged = await staff_a.get(
                            "/api/v1/access/customer",
                            headers={
                                "Cookie": CUSTOMER_COOKIE + "=" + str(staff_token)
                            },
                        )
                        assert forged.status_code == 401
                        customer_token = customer.cookies.get(CUSTOMER_COOKIE)
                        assert (
                            await customer.get(
                                "/api/v1/access/staff",
                                headers={
                                    "Cookie": STAFF_COOKIE + "=" + str(customer_token)
                                },
                            )
                        ).status_code == 401
                        responses = []
                        request_bodies = []
                        for client, company in (
                            (customer, company_ids[0]),
                            (customer, company_ids[1]),
                            (stranger, company_ids[0]),
                        ):
                            body = {
                                    "message": "账号被锁定，请创建工单",
                                    "company_id": company,
                                    "client_request_id": str(uuid4()),
                                }
                            request_bodies.append(body)
                            response = await client.post("/api/v1/agent/chat", json=body)
                            assert response.status_code == 200, response.text
                            responses.append(response.json())
                        first, second, third = responses
                        # 订单分类必须经过真实 ToolNode、入库与工单详情接口完整往返。
                        detail_response = await staff_a.get("/api/v1/tickets/" + first["created_ticket_id"])
                        assert detail_response.json()["category"] == category.value
                        # 完整响应重放不再次运行 Graph、写消息或创建工单。
                        replay = await customer.post("/api/v1/agent/chat", json=request_bodies[0])
                        assert replay.json() == first
                        conflict = await customer.post("/api/v1/agent/chat", json={**request_bodies[0], "message": "更改原请求"})
                        assert conflict.status_code == 409
                        assert conflict.json()["detail"]["code"] == "idempotency_conflict"
                        # 模拟进程在保存最终响应前中断：没有完整响应也不能再次运行 Graph。
                        operation = (await session.scalars(select(ChatOperation).where(
                            ChatOperation.ticket_id == UUID(first["created_ticket_id"])
                        ))).one()
                        saved_response = operation.response
                        operation.response = None
                        operation.status = "running"
                        await session.commit()
                        in_progress = await customer.post("/api/v1/agent/chat", json=request_bodies[0])
                        assert in_progress.status_code == 409
                        assert in_progress.json()["detail"]["outcome"] == "ticket_created"
                        operation.response = saved_response
                        operation.status = "completed"
                        await session.commit()
                        # 相同客户的另一企业、相同企业的另一客户都不能被查询工具读取。
                        query_service = TicketQueryService(session)
                        scope_conversation = UUID(first["conversation_id"])
                        recent = await query_service.search(scope_conversation, TicketQueryInput())
                        assert [item.code for item in recent.items] == [first["created_ticket_code"]]
                        for code in [second["created_ticket_code"], third["created_ticket_code"], "不存在"]:
                            result = await query_service.search(scope_conversation, TicketQueryInput(ticket_code=code))
                            assert result.items == []
                        assert (await query_service.search(scope_conversation, TicketQueryInput(keyword="账号"))).items
                        assert not (await query_service.search(scope_conversation, TicketQueryInput(keyword="%"))).items
                        ticket_query_llm = StubTicketQueryLLM(args={"ticket_code": first["created_ticket_code"]})
                        monkeypatch.setattr("app.services.conversation_service.get_support_graph", lambda: query_graph(ticket_query_llm, checkpointer=graph.checkpointer))
                        queried = await customer.post("/api/v1/agent/chat", json={
                            "message": "我的工单处理到哪了", "company_id": company_ids[0],
                            "conversation_id": first["conversation_id"],
                        })
                        assert queried.status_code == 200, queried.text
                        assert queried.json()["queried_tickets"] is True
                        assert queried.json()["created_ticket_id"] is None
                        history = await customer.get(f"/api/v1/conversations/{scope_conversation}/messages")
                        query_message = next(item for item in history.json() if item["id"] == queried.json()["agent_message_id"])
                        assert query_message["tool_call"] == {
                            "name": "query_support_tickets", "status": "success", "ticket_code": None,
                        }
                        assert "customer_email" not in ticket_query_llm.results[0]
                        assert "activities" not in ticket_query_llm.results[0]
                        # 查询后继续普通聊天，不能残留工具名；实际接口和旧回执重放都应输出 null。
                        general_decider = AsyncMock()
                        general_decider.ainvoke.return_value = decision.model_copy(update={
                            "intent": SupportIntent.GENERAL, "requires_human": False,
                            "should_create_ticket": False, "reply": "王先生您好。",
                        })
                        general_graph = build_support_graph(general_decider, checkpointer=graph.checkpointer)
                        monkeypatch.setattr("app.services.conversation_service.get_support_graph", lambda: general_graph)
                        greeting_request = {"message": "你好我姓王", "company_id": company_ids[0],
                            "conversation_id": first["conversation_id"], "client_request_id": str(uuid4())}
                        greeting = await customer.post("/api/v1/agent/chat", json=greeting_request)
                        assert greeting.status_code == 200, greeting.text
                        assert greeting.json()["executed_tool"] is None
                        assert greeting.json()["created_ticket_id"] is None
                        assert greeting.json()["reply"] == "王先生您好。"
                        # 旧成功回执不能直接透传非法空字符串，也不能因此重复执行 Graph。
                        old_receipt = (await session.scalars(select(ChatOperation).where(
                            ChatOperation.response["agent_message_id"].astext == greeting.json()["agent_message_id"]
                        ))).one()
                        old_receipt.response = {**old_receipt.response, "executed_tool": ""}
                        await session.commit()
                        replayed_greeting = await customer.post("/api/v1/agent/chat", json=greeting_request)
                        assert replayed_greeting.json() == greeting.json()
                        general_decider.ainvoke.assert_awaited_once()
                        monkeypatch.setattr("app.services.conversation_service.get_support_graph", lambda: graph)
                        ticket = first["created_ticket_id"]
                        other_ticket = second["created_ticket_id"]
                        conversation = first["conversation_id"]
                        assert (
                            await stranger.get(
                                f"/api/v1/conversations/{conversation}/messages"
                            )
                        ).status_code == 404
                        assert (
                            await customer.post(
                                "/api/v1/agent/chat",
                                json={
                                    "message": "跨企业追加",
                                    "company_id": company_ids[1],
                                    "conversation_id": conversation,
                                },
                            )
                        ).status_code == 404
                        assert (
                            await stranger.post(
                                "/api/v1/agent/chat",
                                json={
                                    "message": "跨客户追加",
                                    "company_id": company_ids[0],
                                    "conversation_id": conversation,
                                },
                            )
                        ).status_code == 404
                        # 列表、统计、详情、写入、备注、关联消息、运行记录全部覆盖。
                        assert (await staff_a.get("/api/v1/tickets")).json()[
                            "total"
                        ] == 2
                        assert (await staff_b.get("/api/v1/tickets/statistics")).json()[
                            "total"
                        ] == 1
                        assert (
                            await staff_a.get(f"/api/v1/tickets/{other_ticket}")
                        ).status_code == 404
                        assert (
                            await staff_a.patch(
                                f"/api/v1/tickets/{other_ticket}",
                                json={"status": "in_progress"},
                            )
                        ).status_code == 404
                        assert (
                            await staff_a.post(
                                f"/api/v1/tickets/{other_ticket}/notes",
                                json={"content": "越权备注"},
                            )
                        ).status_code == 404
                        assert (
                            await staff_a.get(
                                f"/api/v1/tickets/{other_ticket}/messages"
                            )
                        ).status_code == 404
                        assert (
                            await staff_b.get(
                                f"/api/v1/staff/conversations/{conversation}/messages"
                            )
                        ).status_code == 404
                        # 新增一轮普通聊天，成功回执重放不再增加运行记录。
                        assert (await staff_a.get("/api/v1/agent-runs")).json()[
                            "total"
                        ] == 4
                        assert (
                            await staff_a.get("/api/v1/agent-runs/statistics")
                        ).json()["total"] == 4
                        query_run = await staff_a.get("/api/v1/agent-runs/" + queried.json()["agent_run_id"])
                        assert query_run.json()["tool_name"] == "query_support_tickets"
                        assert (
                            await staff_a.get(
                                "/api/v1/agent-runs/" + second["agent_run_id"]
                            )
                        ).status_code == 404
                        spoof = await staff_a.post(
                            "/api/v1/tickets",
                            json={
                                "title": "跨企业建单",
                                "description": "不允许",
                                "conversation_id": second["conversation_id"],
                            },
                        )
                        assert spoof.status_code == 404
                        updated = await staff_a.patch(
                            f"/api/v1/tickets/{ticket}",
                            json={"status": "in_progress", "operator_name": "伪造姓名"},
                        )
                        assert updated.status_code == 200
                        assert all(
                            item["operator_name"] != "伪造姓名"
                            for item in updated.json()["activities"]
                        )
                        own = (await customer.get("/api/v1/customer/tickets")).json()
                        assert own["total"] == 2
                        assert {item["company_id"] for item in own["items"]} == set(
                            company_ids
                        )
                        assert third["created_ticket_id"] not in {
                            item["id"] for item in own["items"]
                        }
                        assert all("activities" not in item for item in own["items"])
                        assert (
                            len((await staff_a.get("/api/v1/staff/customers")).json())
                            == 2
                        )
                        assert (
                            len((await staff_b.get("/api/v1/staff/customers")).json())
                            == 1
                        )
                        history = await customer.get(
                            "/api/v1/customer/conversations",
                            params={"company_id": company_ids[0]},
                        )
                        assert [item["id"] for item in history.json()] == [conversation]
                        # 模拟工单已提交、最终回复保存失败：必须返回真实编号，重放不能再建单。
                        original_add = ConversationRepository.add_message

                        async def fail_agent_reply(repository, conversation_id, role, content, **kwargs):
                            if role == MessageRole.AGENT:
                                raise RuntimeError("模拟回复写入失败")
                            return await original_add(repository, conversation_id, role, content, **kwargs)

                        with monkeypatch.context() as failure_patch:
                            failure_patch.setattr(ConversationRepository, "add_message", fail_agent_reply)
                            failed_body = {"message": "请创建登录故障工单", "company_id": company_ids[0], "client_request_id": str(uuid4())}
                            failed = await customer.post("/api/v1/agent/chat", json=failed_body)
                            assert failed.status_code == 502, failed.text
                            detail = failed.json()["detail"]
                            assert detail["outcome"] == "ticket_created"
                            assert detail["ticket_code"]
                            assert detail["retryable"] is False
                            repeated = await customer.post("/api/v1/agent/chat", json=failed_body)
                            assert repeated.json()["detail"]["ticket_code"] == detail["ticket_code"]
                            assert (await customer.get("/api/v1/customer/tickets")).json()["total"] == 3

                        # 模型调用前失败可以明确说明未建单，并允许用户用新键发起下一次尝试。
                        with monkeypatch.context() as failure_patch:
                            def unavailable_graph():
                                raise TimeoutError("模拟模型连接超时")

                            failure_patch.setattr("app.services.conversation_service.get_support_graph", unavailable_graph)
                            timeout_body = {"message": "查询进度", "company_id": company_ids[0], "client_request_id": str(uuid4())}
                            timed_out = await customer.post("/api/v1/agent/chat", json=timeout_body)
                            assert timed_out.status_code == 504
                            assert timed_out.json()["detail"]["outcome"] == "not_executed"
                            assert timed_out.json()["detail"]["retryable"] is True
                            assert "模拟模型连接超时" not in timed_out.text
                            assert (await customer.post("/api/v1/agent/chat", json=timeout_body)).status_code == 504

                        # 退出在数据库撤销，重放旧 Cookie 无效；不是只删除浏览器变量。
                        await staff_a.post("/api/v1/access/staff/logout")
                        assert (
                            await staff_a.get(
                                "/api/v1/access/staff",
                                headers={
                                    "Cookie": STAFF_COOKIE + "=" + str(staff_token)
                                },
                            )
                        ).status_code == 401
                        token = stranger.cookies.get(CUSTOMER_COOKIE)
                        record = await session.get(
                            LoginSession, token_digest(str(token))
                        )
                        assert record is not None
                        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                        await session.commit()
                        assert (
                            await stranger.get("/api/v1/customer/tickets")
                        ).status_code == 401
                        await customer.post("/api/v1/access/customer/logout")
                        assert (
                            await customer.get(
                                "/api/v1/access/customer",
                                headers={
                                    "Cookie": CUSTOMER_COOKIE
                                    + "="
                                    + str(customer_token)
                                },
                            )
                        ).status_code == 401
                        limiter = AuthRepository(session)
                        key = token_digest("rate-test-" + suffix)
                        for _ in range(30):
                            assert await limiter.consume_attempt(key)
                        assert not await limiter.consume_attempt(key)
            finally:
                await transaction.rollback()
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
