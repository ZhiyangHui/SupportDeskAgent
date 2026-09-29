"""真实 pgvector 检索验证企业隔离、发布开关、模型指纹及失败回滚；所有业务数据回滚。"""
import os
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.access import require_staff
from app.core.config import get_settings
from app.db.models import Company
from app.db.session import get_db_session
from app.main import create_app
from app.schema.access import Principal
from app.schema.knowledge import DraftChunk, DraftUpdate, KnowledgeCreate
from app.services.knowledge_service import KnowledgeService, KnowledgeUnavailableError


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("SUPPORT_TEST_DATABASE") != "1", reason="需要本地 PostgreSQL")
async def test_index_search_scope_and_rollback(monkeypatch):
    settings = get_settings().model_copy(update={"embedding_dimensions": 3, "embedding_model": "test", "embedding_base_url": "http://embedding.invalid", "knowledge_min_score": 0.5})
    assert "127.0.0.1" in settings.database_url or "localhost" in settings.database_url
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
                    a, b = Company(code=uuid4().hex, name="甲企业"), Company(code=uuid4().hex, name="乙企业")
                    session.add_all([a, b])
                    await session.flush()
                    a_id, b_id = a.id, b.id
                    first, other = KnowledgeService(session, a_id), KnowledgeService(session, b_id)
                    doc = await first.create(KnowledgeCreate(title="甲政策", content="签收七天内未使用可退货。"))
                    doc_id = doc.id
                    assert await first.search("退货") == []
                    embeddings.aembed_query.assert_not_awaited()
                    await first.prepare(doc_id, 0)
                    await first.publish(doc_id, 1)
                    # 保存草稿不改变线上检索；同模型下发布失败也必须保留旧片段。
                    calls = embeddings.aembed_documents.await_count
                    await first.save_draft(doc_id, DraftUpdate(revision=1, chunks=[DraftChunk(heading_path="甲政策 / 新规则", content="新的待发布内容")]))
                    assert embeddings.aembed_documents.await_count == calls
                    assert "签收七天" in (await first.search("退货"))[0].content
                    embeddings.aembed_documents.side_effect = RuntimeError("synthetic draft publish failure")
                    with pytest.raises(KnowledgeUnavailableError):
                        await first.publish(doc_id, 2)
                    assert "签收七天" in (await first.search("退货"))[0].content
                    # 恢复自动草稿后继续原有多企业、多模型测试。
                    embeddings.aembed_documents.side_effect = lambda texts: [[1, 0, 0] for _ in texts]
                    await first.prepare(doc_id, 2)
                    await first.publish(doc_id, 3)
                    alien = await other.create(KnowledgeCreate(title="乙政策", content="其他企业的秘密资料"))
                    alien_id = alien.id
                    await other.prepare(alien_id, 0)
                    await other.publish(alien_id, 1)
                    hits = await first.search("退货")
                    assert len(hits) == 1 and hits[0].title == "甲政策"
                    with pytest.raises(LookupError):
                        await other.owned(doc_id)
                    row = await first.owned(doc_id, lock=True)
                    row.published = False
                    await session.commit()
                    assert await first.search("退货") == []
                    await first.publish(doc_id, 3)
                    # 换模型后旧索引不参与检索；重建失败不能损坏原索引。
                    settings.embedding_model = "another-model"
                    assert await first.search("退货") == []
                    embeddings.aembed_documents.side_effect = RuntimeError("synthetic failure")
                    with pytest.raises(KnowledgeUnavailableError):
                        await first.publish(doc_id, 3)
                    settings.embedding_model = "test"
                    assert len(await first.search("退货")) == 1
                    # 不同维度、同一表的历史向量也不能导致新模型距离计算报错。
                    settings.embedding_model, settings.embedding_dimensions = "two-dimensions", 2
                    embeddings.aembed_documents.side_effect = lambda texts: [[1, 0] for _ in texts]
                    embeddings.aembed_query.return_value = [1, 0]
                    new_doc = await first.create(KnowledgeCreate(title="新模型政策", content="新的公开政策"))
                    await first.prepare(new_doc.id, 0)
                    await first.publish(new_doc.id, 1)
                    assert [hit.title for hit in await first.search("政策")] == ["新模型政策"]
                    app = create_app()
                    async def database():
                        yield session
                    app.dependency_overrides[get_db_session] = database
                    app.dependency_overrides[require_staff] = lambda: Principal(id=uuid4(), audience="staff", company_id=a_id, display_name="测试客服")
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                        listing = await client.get("/api/v1/staff/knowledge")
                        assert listing.status_code == 200
                        assert all(row["title"] != "乙政策" for row in listing.json())
                        # 详情包含原文和实际入库片段，但不能泄露向量或其他企业资料。
                        detail = await client.get(f"/api/v1/staff/knowledge/{doc_id}")
                        assert detail.status_code == 200
                        assert detail.json()["content"] == "签收七天内未使用可退货。"
                        assert detail.json()["chunks"][0]["position"] == 1
                        assert "embedding" not in detail.json()["chunks"][0]
                        assert detail.json()["chunks"][0]["heading_path"] == "甲政策"
                        assert (await client.post(f"/api/v1/staff/knowledge/{doc_id}/publish", json={"revision": 0})).status_code == 409
                        assert (await client.put(f"/api/v1/staff/knowledge/{alien_id}/draft", json={"revision": 1, "chunks": [{"heading_path": "政策", "content": "恶意覆盖"}]})).status_code == 404
                        assert (await client.get(f"/api/v1/staff/knowledge/{alien_id}")).status_code == 404
                        assert (await client.post(f"/api/v1/staff/knowledge/{alien_id}/disable")).status_code == 404
                        assert (await client.post("/api/v1/staff/knowledge/upload", files={"file": ("guide.pdf", b"fake pdf")})).status_code == 422
                        assert (await client.post("/api/v1/staff/knowledge/upload", files={"file": ("guide.txt", b"a" * 240001)})).status_code == 413
                        uploaded = await client.post("/api/v1/staff/knowledge/upload", files={"file": ("guide.md", "# 公开说明\n保修一年".encode())})
                        assert uploaded.status_code == 200 and uploaded.json()["published"] is False
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()
