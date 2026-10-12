"""真实 Neo4j 验证：只写随机知识包，结束时只清理本次测试命名空间。"""
import os
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.db.knowledge_graph import (
    GraphRevisionConflict,
    GraphUnavailableError,
    KnowledgeGraphStore,
    fingerprint,
)
from app.knowledge.domain_catalog import load_domain_catalog
from app.schema.knowledge_graph import DomainCatalog

pytestmark = pytest.mark.skipif(os.getenv("SUPPORT_TEST_GRAPH") != "1", reason="需显式开启本机 Neo4j 集成测试")


@pytest.mark.asyncio
async def test_versioned_paths_idempotency_scope_and_integrity():
    from neo4j import AsyncGraphDatabase
    settings = get_settings()
    assert "127.0.0.1" in settings.neo4j_uri or "localhost" in settings.neo4j_uri
    a, b = "test-" + uuid4().hex, "test-" + uuid4().hex
    base = load_domain_catalog().model_copy(update={"id": a})
    async with AsyncGraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password)) as driver:
        store = KnowledgeGraphStore(driver, settings.neo4j_database)
        await store.initialize()
        try:
            await store.publish(base)
            await store.publish(base)
            await store.publish(base.model_copy(update={"id": b}))
            snapshot = await store.read(a)
            assert fingerprint(snapshot) == fingerprint(base)
            assert next(p for p in snapshot.paths if p.id == "keyboard-receiver-path").checks == ["check-receiver", "check-connection"]
            # 同症状的两个原因必须各自保留条件，不允许错误拼接解法。
            assert {tuple(p.requires) for p in snapshot.paths} == {tuple(p.requires) for p in base.paths}
            changed = base.model_dump()
            changed["nodes"][0]["description"] += "（更新）"
            with pytest.raises(GraphRevisionConflict):
                await store.publish(DomainCatalog.model_validate(changed))
            assert fingerprint(await store.read(a)) == fingerprint(base)
            changed["version"] = 2
            newer = DomainCatalog.model_validate(changed)
            await store.publish(newer)
            assert (await store.read(a)).version == 2
            assert (await store.read(b)).version == 1
            with pytest.raises(GraphRevisionConflict):
                await store.publish(base)
            # 管理员在 Neo4j 直接改数据也不能静默改变知识：读取会核对发布指纹。
            await driver.execute_query("MATCH (n:DomainConcept {catalog: $catalog, version: 2, id: 'wireless-keyboard'}) SET n.description = '意外修改'", catalog=a, database_=settings.neo4j_database)
            with pytest.raises(GraphUnavailableError, match="不一致"):
                await store.read(a)
        finally:
            await driver.execute_query("MATCH (n) WHERE (n:DomainConcept OR n:DomainPath OR n:DomainRelease) AND n.catalog IN $ids DETACH DELETE n", ids=[a, b], database_=settings.neo4j_database)
            await driver.execute_query("MATCH (n:DomainCatalog) WHERE n.id IN $ids DETACH DELETE n", ids=[a, b], database_=settings.neo4j_database)
