"""经验沉淀的隐私、审核及租户边界；向量供应商全部使用替身。"""
import os
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.access import require_staff
from app.core.config import get_settings
from app.db.identity_models import Company, CustomerAccount, StaffAccount
from app.db.models import Ticket, TicketStatus
from app.db.session import get_db_session
from app.main import create_app
from app.schema.access import Principal
from app.services.knowledge_service import KnowledgeService
from app.services.ticket_experience_service import redact_experience


def test_redaction_is_repeatable_and_preserves_product():
    raw = "王小明的X999，电话13812345678，邮件test@example.com，订单MO-123，身份证110101199001011234"
    safe = redact_experience(raw, ["王小明"])
    assert "X999" in safe
    for secret in ("王小明", "13812345678", "test@example.com", "MO-123", "110101199001011234"):
        assert secret not in safe
    assert redact_experience(safe, ["王小明"]) == safe


@pytest.mark.asyncio
@pytest.mark.parametrize("completed_status", [TicketStatus.RESOLVED, TicketStatus.CLOSED])
@pytest.mark.skipif(os.getenv("SUPPORT_TEST_DATABASE") != "1", reason="需要本地 PostgreSQL")
async def test_case_review_publish_scope_and_privacy(monkeypatch, completed_status):
    settings = get_settings().model_copy(update={"embedding_dimensions": 3, "embedding_model": "case-test", "embedding_base_url": "http://embedding.invalid"})
    assert "localhost" in settings.database_url or "127.0.0.1" in settings.database_url
    monkeypatch.setattr("app.services.knowledge_service.get_settings", lambda: settings)
    embeddings = AsyncMock()
    embeddings.aembed_documents.side_effect = lambda texts: [[1, 0, 0] for _ in texts]
    embeddings.aembed_query.return_value = [1, 0, 0]
    monkeypatch.setattr("app.services.knowledge_service.embedding_client", lambda: embeddings)
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
                    company, other = Company(code=uuid4().hex, name="甲"), Company(code=uuid4().hex, name="乙")
                    customer = CustomerAccount(username=uuid4().hex, display_name="王小明", password_hash="unused")
                    session.add_all([company, other, customer])
                    await session.flush()
                    staff = StaffAccount(company_id=company.id, username="reviewer", display_name="审核客服", password_hash="unused")
                    ticket = Ticket(company_id=company.id, customer_id=customer.id, code=f"TK-{uuid4().hex[:12]}", title="含隐私的原始标题", description="客户地址及内部备注不能自动导入", status=TicketStatus.OPEN)
                    session.add_all([staff, ticket])
                    await session.commit()
                    staff_id, company_id, ticket_id, other_id = staff.id, company.id, ticket.id, other.id
                    payload = {"ticket_code": ticket.code, "title": "键盘断连案例", "symptom": "王小明的键盘断连，电话13812345678", "cause": "接收器松动", "solution": "重新插入后恢复", "applicability": "仅供接触不良排查参考"}
                    app = create_app()
                    async def database():
                        yield session
                    app.dependency_overrides[get_db_session] = database
                    app.dependency_overrides[require_staff] = lambda: Principal(id=staff_id, audience="staff", company_id=company_id, display_name="审核客服")
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                        base = "/api/v1/staff/knowledge"
                        assert (await client.get(base + "/ticket-experiences/candidates")).json() == []
                        assert (await client.get(base + "/ticket-experiences/source", params={"code": ticket.code})).status_code == 409
                        assert (await client.post(base + "/ticket-experiences", json=payload)).status_code == 409
                        ticket.status = completed_status
                        await session.commit()
                        options = (await client.get(base + "/ticket-experiences/candidates")).json()
                        assert [option["code"] for option in options] == [ticket.code]
                        source = (await client.get(base + "/ticket-experiences/source", params={"code": ticket.code})).json()
                        assert source["description"] == ticket.description
                        assert "customer_id" not in source and "activities" not in source
                        assert (await client.get(base + "/ticket-experiences/candidates", params={"keyword": "无匹配内容"})).json() == []
                        created = await client.post(base + "/ticket-experiences", json=payload)
                        assert created.status_code == 200, created.text
                        doc = created.json()["id"]
                        assert created.json()["source_kind"] == "ticket_case" and not created.json()["published"]
                        assert (await client.post(base + "/ticket-experiences", json=payload)).status_code == 409
                        detail = (await client.get(f"{base}/{doc}")).json()
                        assert "王小明" not in detail["content"] and "13812345678" not in detail["content"]
                        assert "客户地址及内部备注" not in detail["content"]
                        assert detail["source_ticket_id"] == str(ticket_id)
                        assert (await client.post(f"{base}/{doc}/preview", json={"revision": 0})).status_code == 200
                        embeddings.aembed_documents.assert_not_awaited()
                        assert await KnowledgeService(session, company_id).search("断连") == []
                        assert (await client.post(f"{base}/{doc}/publish", json={"revision": 1})).status_code == 409
                        assert (await client.post(f"{base}/{doc}/publish", json={"revision": 1, "confirm_case_review": True})).status_code == 200
                        hits = await KnowledgeService(session, company_id).search("断连")
                        assert hits and all(hit.source_kind == "ticket_case" for hit in hits)
                        assert all("历史案例" in hit.content for hit in hits)
                        assert all("source_ticket_id" not in hit.model_dump() for hit in hits)
                        assert await KnowledgeService(session, other_id).search("断连") == []
                        # 编辑后重新带入隐私，即使勾选审核也拒绝发布，原索引保持可用。
                        edited = {"revision": 1, "chunks": [{"heading_path": "经验", "content": "联系13812345678"}]}
                        assert (await client.put(f"{base}/{doc}/draft", json=edited)).status_code == 200
                        assert (await client.post(f"{base}/{doc}/publish", json={"revision": 2, "confirm_case_review": True})).status_code == 409
                        assert await KnowledgeService(session, company_id).search("断连")
                        assert (await client.post(f"{base}/{doc}/disable")).status_code == 200
                        assert await KnowledgeService(session, company_id).search("断连") == []
                        app.dependency_overrides[require_staff] = lambda: Principal(id=uuid4(), audience="staff", company_id=other_id, display_name="其他企业")
                        assert (await client.get(base + "/ticket-experiences/candidates")).json() == []
                        assert (await client.get(base + "/ticket-experiences/source", params={"code": payload["ticket_code"]})).status_code == 404
                        assert (await client.get(f"{base}/{doc}")).status_code == 404
                        assert (await client.post(base + "/ticket-experiences", json=payload)).status_code == 404
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()
