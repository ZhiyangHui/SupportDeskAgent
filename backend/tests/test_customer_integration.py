"""真实数据库的双账号、双企业、双客户闭环，所有测试写入由外层事务回滚。"""

import os
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.agent.graph import DecisionModel, ToolCallingModel, build_support_graph
from app.agent.schemas import (
    AgentDecision,
    SupportIntent,
    TicketCategory,
    TicketPriority,
)
from app.core.access import CUSTOMER_COOKIE, STAFF_COOKIE
from app.core.config import get_settings
from app.db.auth_repository import AuthRepository
from app.db.identity_models import LoginSession
from app.db.session import get_db_session
from app.main import create_app
from app.services.auth_service import token_digest
from tests.test_agent_graph import StubDecisionModel, StubTicketCallingModel


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("SUPPORT_TEST_DATABASE") != "1", reason="显式启用本地数据库集成测试"
)
async def test_dual_auth_multitenant_ticket_flow(monkeypatch):
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
        ticket_category=TicketCategory.ACCOUNT,
        reason="客户要求建单",
        reply="正在创建工单",
    )
    graph = build_support_graph(
        cast(DecisionModel, StubDecisionModel(decision)),
        cast(ToolCallingModel, StubTicketCallingModel()),
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
                        for client, company in (
                            (customer, company_ids[0]),
                            (customer, company_ids[1]),
                            (stranger, company_ids[0]),
                        ):
                            response = await client.post(
                                "/api/v1/agent/chat",
                                json={
                                    "message": "账号被锁定，请创建工单",
                                    "company_id": company,
                                },
                            )
                            assert response.status_code == 200, response.text
                            responses.append(response.json())
                        first, second, third = responses
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
                        assert (await staff_a.get("/api/v1/agent-runs")).json()[
                            "total"
                        ] == 2
                        assert (
                            await staff_a.get("/api/v1/agent-runs/statistics")
                        ).json()["total"] == 2
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
