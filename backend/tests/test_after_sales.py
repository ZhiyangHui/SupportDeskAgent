"""售后预判从真实 HTTP 入口验证，只有外部模型和向量服务使用替身。"""

import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.agent.graph import build_support_graph
from app.agent.memory.order_memory import OrderTurn
from app.agent.memory.persistence import create_memory_serializer
from app.agent.schemas import AgentDecision
from app.core.access import customer_identity, require_staff
from app.core.config import get_settings
from app.db.models import Company, CustomerAccount
from app.db.session import get_db_session
from app.main import create_app
from app.schema.access import Principal
from app.schema.after_sales import AfterSalesAssessment
from app.schema.knowledge import KnowledgeCreate
from app.services.knowledge_service import KnowledgeService

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("SUPPORT_TEST_DATABASE") != "1", reason="需要本地数据库"
    ),
]


@pytest_asyncio.fixture
async def scenario(monkeypatch):
    settings = get_settings().model_copy(
        update={
            "knowledge_enabled": True,
            "embedding_dimensions": 3,
            "embedding_model": "test",
            "embedding_base_url": "http://embedding.invalid",
            "knowledge_min_score": 0.5,
        }
    )
    assert "localhost" in settings.database_url or "127.0.0.1" in settings.database_url
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setattr("app.services.knowledge_service.get_settings", lambda: settings)
    vectors = AsyncMock()
    vectors.aembed_documents.side_effect = lambda texts: [[1, 0, 0] for _ in texts]
    vectors.aembed_query.return_value = [1, 0, 0]
    monkeypatch.setattr(
        "app.services.knowledge_service.embedding_client", lambda: vectors
    )
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
                    company = Company(code=uuid4().hex, name="售后测试企业")
                    customer = CustomerAccount(
                        username=uuid4().hex,
                        display_name="测试客户",
                        password_hash="unused",
                    )
                    session.add_all([company, customer])
                    await session.commit()
                    company_id, customer_id = company.id, customer.id
                    app = create_app()

                    async def db():
                        yield session

                    app.dependency_overrides[get_db_session] = db
                    app.dependency_overrides[customer_identity] = lambda: Principal(
                        id=customer_id, audience="customer", display_name="测试客户"
                    )
                    app.dependency_overrides[require_staff] = lambda: Principal(
                        id=uuid4(),
                        audience="staff",
                        company_id=company_id,
                        display_name="测试员工",
                    )
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app), base_url="http://test"
                    ) as client:
                        yield client, company_id, session
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()


async def test_policy_question_does_not_create_ticket_before_confirmation(
    scenario, monkeypatch
):
    client, company_id, session = scenario
    orders = (
        await client.get(f"/api/v1/customer/companies/{company_id}/orders")
    ).json()["items"]
    keyboard = next(row for row in orders if row["product_name"] == "无线键盘")
    knowledge = KnowledgeService(session, company_id)
    doc = await knowledge.create(
        KnowledgeCreate(
            title="键盘退货规则",
            content="无线键盘签收次日起七天内，商品配件完整、无人为损坏可以申请退货。",
        )
    )
    await knowledge.prepare(doc.id, 0)
    await knowledge.publish(doc.id, 1)
    decider = AsyncMock()
    decider.ainvoke.return_value = AgentDecision(
        intent="order",
        priority="medium",
        requires_human=False,
        should_create_ticket=False,
        needs_ticket_details=False,
        needs_order_lookup=True,
        order_turn=OrderTurn(action="new", reference=keyboard["code"], issue="退货"),
        reason="先核实能否申请退货",
        reply="核实订单规则",
    )
    graph = build_support_graph(
        decider, checkpointer=InMemorySaver(serde=create_memory_serializer())
    )
    monkeypatch.setattr(
        "app.services.conversation_service.get_support_graph", lambda: graph
    )
    response = await client.post(
        "/api/v1/agent/chat",
        json={
            "company_id": str(company_id),
            "message": "这个无线键盘能退吗？可以的话帮我提交申请",
            "client_request_id": str(uuid4()),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["created_ticket_id"] is None
    assert "签收" in response.json()["reply"]


async def test_received_date_is_optional_validated_and_idempotent(scenario):
    client, company_id, _ = scenario
    path = f"/api/v1/customer/companies/{company_id}/orders"
    existing = (await client.get(path)).json()["items"]
    assert all(row.get("received_on") is None for row in existing)
    body = {
        "product_name": "无线键盘",
        "amount": "199.00",
        "status": "completed",
        "received_on": (
            datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=2)
        ).isoformat(),
        "client_request_id": str(uuid4()),
    }
    response = await client.post(path, json=body)
    assert response.status_code == 201, response.text
    assert response.json()["received_on"] == body["received_on"]
    assert (await client.post(path, json=body)).json()["id"] == response.json()["id"]
    assert (
        await client.post(
            path,
            json={
                **body,
                "received_on": datetime.now(ZoneInfo("Asia/Shanghai"))
                .date()
                .isoformat(),
            },
        )
    ).status_code == 409
    for changes in (
        {
            "received_on": (
                datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)
            ).isoformat()
        },
        {"status": "paid"},
    ):
        assert (
            await client.post(
                path, json={**body, **changes, "client_request_id": str(uuid4())}
            )
        ).status_code == 422


async def prepare_assessment(scenario, monkeypatch, *, publish=True):
    """用真实订单和已发布政策搭场景，替身只负责外部模型输出。"""
    client, company_id, session = scenario
    row = await client.post(
        f"/api/v1/customer/companies/{company_id}/orders",
        json={
            "product_name": "无线键盘",
            "amount": "199.00",
            "status": "completed",
            "received_on": (
                datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=2)
            ).isoformat(),
            "client_request_id": str(uuid4()),
        },
    )
    assert row.status_code == 201
    knowledge = KnowledgeService(session, company_id)
    doc = await knowledge.create(
        KnowledgeCreate(
            title="无线键盘退货规则",
            content="无线键盘签收次日起七天内，配件齐全且无人为损坏可申请退货，最终由客服审核。",
        )
    )
    if publish:
        await knowledge.prepare(doc.id, 0)
        await knowledge.publish(doc.id, 1)
    decider, assessor = AsyncMock(), AsyncMock()
    decider.ainvoke.return_value = AgentDecision(
        intent="order",
        priority="medium",
        requires_human=False,
        should_create_ticket=False,
        needs_ticket_details=False,
        needs_order_lookup=True,
        order_turn=OrderTurn(
            action="new", reference=row.json()["code"], issue="退货", assess=True
        ),
        reason="核实退货条件",
        reply="核实中",
    )
    assessor.ainvoke.return_value = AfterSalesAssessment(
        verdict="needs_info",
        explanation="签收时间在申请期限内。",
        questions=["配件是否齐全、有无人为损坏？"],
        source_numbers=[1],
    )
    graph = build_support_graph(
        decider,
        after_sales_llm=assessor,
        checkpointer=InMemorySaver(serde=create_memory_serializer()),
    )
    monkeypatch.setattr(
        "app.services.conversation_service.get_support_graph", lambda: graph
    )
    return row.json(), knowledge, doc.id, decider, assessor


async def test_assessment_followup_confirmation_and_duplicate_submission(
    scenario, monkeypatch
):
    client, company_id, _ = scenario
    order, _, _, decider, assessor = await prepare_assessment(scenario, monkeypatch)
    first = await client.post(
        "/api/v1/agent/chat",
        json={
            "company_id": str(company_id),
            "message": "我的无线键盘能退吗？可以的话帮我申请",
            "client_request_id": str(uuid4()),
        },
    )
    assert first.status_code == 200, first.text
    assert "配件" in first.json()["reply"] and first.json()["created_ticket_id"] is None
    conversation_id = first.json()["conversation_id"]

    async def chat(message, request_id=None):
        response = await client.post(
            "/api/v1/agent/chat",
            json={
                "company_id": str(company_id),
                "conversation_id": conversation_id,
                "message": message,
                "client_request_id": request_id or str(uuid4()),
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    decider.ainvoke.return_value = decider.ainvoke.return_value.model_copy(
        update={
            "order_turn": OrderTurn(action="continue", facts="配件齐全，无人为损坏")
        }
    )
    assessor.ainvoke.return_value = AfterSalesAssessment(
        verdict="eligible",
        explanation="按您补充的情况，可以提交退货申请供客服审核。",
        source_numbers=[1],
    )
    preview = await chat("配件齐全，没有人为损坏")
    assert preview["created_ticket_id"] is None
    assert "确认提交" in preview["reply"] and order["code"] in preview["reply"]
    assert "无线键盘退货规则" in preview["reply"]
    request_id = str(uuid4())
    result = await chat("确认提交", request_id)
    assert result["created_ticket_id"]
    assert (await chat("确认提交", request_id)) == result
    tickets = (await client.get("/api/v1/customer/tickets")).json()
    assert tickets["total"] == 1
    assert tickets["items"][0]["id"] == result["created_ticket_id"]
    assert "配件齐全" in tickets["items"][0]["description"]
    assert tickets["items"][0]["desired_resolution"] == "退货"
    run = (await client.get(f"/api/v1/agent-runs/{result['agent_run_id']}")).json()
    assert [step["name"] for step in run["steps"] if step["kind"] == "tool"] == [
        "query_my_orders",
        "search_company_knowledge",
        "create_order_ticket",
    ]
    assert all(step["status"] == "succeeded" for step in run["steps"])
    # 换请求标识再次确认也不得复用已完成草稿创建第二张工单。
    repeated = await chat("确认提交")
    assert repeated["created_ticket_id"] is None
    assert (await client.get("/api/v1/customer/tickets")).json()["total"] == 1


@pytest.mark.parametrize(
    "outcome",
    [
        "no_policy",
        "manual",
        "invalid_citation",
        "cancel",
        "policy_disabled",
        "model_timeout",
    ],
)
async def test_assessment_stops_without_authorized_write(
    scenario, monkeypatch, outcome
):
    client, company_id, _ = scenario
    _, knowledge, doc_id, _, assessor = await prepare_assessment(
        scenario, monkeypatch, publish=outcome != "no_policy"
    )
    assessor.ainvoke.return_value = AfterSalesAssessment(
        verdict="manual" if outcome == "manual" else "eligible",
        explanation="请客服核实商品情况。" if outcome == "manual" else "可提交审核。",
        source_numbers=[99] if outcome == "invalid_citation" else [1],
    )
    if outcome == "model_timeout":
        assessor.ainvoke.side_effect = TimeoutError("synthetic timeout")
    first = await client.post(
        "/api/v1/agent/chat",
        json={
            "company_id": str(company_id),
            "message": "我的订单能退吗",
            "client_request_id": str(uuid4()),
        },
    )
    assert first.status_code == 200, first.text
    result = first.json()
    if outcome in {"cancel", "policy_disabled"}:
        if outcome == "policy_disabled":
            row = await knowledge.owned(doc_id, lock=True)
            row.published = False
            await knowledge.session.commit()
        followup = await client.post(
            "/api/v1/agent/chat",
            json={
                "company_id": str(company_id),
                "conversation_id": result["conversation_id"],
                "message": "取消" if outcome == "cancel" else "确认提交",
                "client_request_id": str(uuid4()),
            },
        )
        assert followup.status_code == 200, followup.text
        result = followup.json()
    assert result["created_ticket_id"] is None
    assert result["requires_human"] is (outcome != "cancel")
    assert (await client.get("/api/v1/customer/tickets")).json()["total"] == 0


@pytest.mark.parametrize("scope", ["company", "customer"])
async def test_foreign_order_cannot_be_assessed_or_submitted(
    scenario, monkeypatch, scope
):
    """即使模型给出了别人的订单编号，真实工具仍必须按会话身份重新查询。"""
    from app.db.order_models import DemoOrder

    client, company_id, session = scenario
    _, _, _, decider, _ = await prepare_assessment(scenario, monkeypatch)
    identity = (await client.get("/api/v1/access/customer")).json()
    foreign_company = Company(code=uuid4().hex, name="其他企业")
    foreign_customer = CustomerAccount(
        username=uuid4().hex, display_name="其他客户", password_hash="unused"
    )
    session.add_all([foreign_company, foreign_customer])
    await session.flush()
    from uuid import UUID

    foreign = DemoOrder(
        company_id=foreign_company.id if scope == "company" else company_id,
        customer_id=UUID(identity["id"]) if scope == "company" else foreign_customer.id,
        code="MO-" + uuid4().hex,
        product_name="不可泄露的订单商品",
        amount=199,
        status="completed",
    )
    session.add(foreign)
    await session.commit()
    decider.ainvoke.return_value = decider.ainvoke.return_value.model_copy(
        update={
            "order_turn": OrderTurn(
                action="new", reference=foreign.code, issue="退货", assess=True
            )
        }
    )
    result = await client.post(
        "/api/v1/agent/chat",
        json={
            "company_id": str(company_id),
            "message": "请判断这笔订单能否退货",
            "client_request_id": str(uuid4()),
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["created_ticket_id"] is None
    assert "不可泄露的订单商品" not in result.json()["reply"]
    assert "确认提交" not in result.json()["reply"]
    assert (await client.get("/api/v1/customer/tickets")).json()["total"] == 0


async def test_changed_policy_requires_a_second_confirmation(scenario, monkeypatch):
    """预览不是永久授权：确认时政策变动，应展示新结论而非直接沿用旧草稿。"""
    client, company_id, _ = scenario
    _, knowledge, _, _, assessor = await prepare_assessment(scenario, monkeypatch)
    assessor.ainvoke.return_value = AfterSalesAssessment(
        verdict="eligible", explanation="可提交审核。", source_numbers=[1]
    )
    first = await client.post(
        "/api/v1/agent/chat",
        json={
            "company_id": str(company_id),
            "message": "我的无线键盘能退吗",
            "client_request_id": str(uuid4()),
        },
    )
    assert "确认提交" in first.json()["reply"]
    # 用正式发布流程加入一条补充政策；不直接改向量表或伪造 Graph 状态。
    extra = await knowledge.create(
        KnowledgeCreate(
            title="补充政策", content="无线键盘退货还需保留包装，缺少包装请人工核实。"
        )
    )
    await knowledge.prepare(extra.id, 0)
    await knowledge.publish(extra.id, 1)
    result = await client.post(
        "/api/v1/agent/chat",
        json={
            "company_id": str(company_id),
            "conversation_id": first.json()["conversation_id"],
            "message": "确认提交",
            "client_request_id": str(uuid4()),
        },
    )
    assert result.status_code == 200, result.text
    assert "重新确认" in result.json()["reply"]
    assert result.json()["created_ticket_id"] is None
    assert (await client.get("/api/v1/customer/tickets")).json()["total"] == 0
