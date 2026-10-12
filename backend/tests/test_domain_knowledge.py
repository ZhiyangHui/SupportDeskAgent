"""领域知识结构与只读访问测试，不调用模型、不连接真实图数据库。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.access import require_staff
from app.core.config import Settings
from app.db.knowledge_graph import GraphUnavailableError, fingerprint, graph_lifespan
from app.knowledge.domain_catalog import load_domain_catalog
from app.main import create_app
from app.schema.access import Principal
from app.schema.knowledge_graph import DomainCatalog


@pytest.mark.parametrize("invalid", ["missing", "wrong_kind", "duplicate", "contradiction", "orphan", "unordered_duplicate", "private_data"])
def test_invalid_knowledge_is_rejected(invalid):
    data = load_domain_catalog().model_dump()
    if invalid == "missing":
        data["paths"][0]["cause"] = "nonexistent"
    elif invalid == "wrong_kind":
        data["paths"][0]["solution"] = "wireless-keyboard"
    elif invalid == "duplicate":
        data["nodes"].append(data["nodes"][0])
    elif invalid == "contradiction":
        data["paths"][0]["excludes"].append(data["paths"][0]["requires"][0])
    elif invalid == "orphan":
        data["nodes"].append({**data["nodes"][0], "id": "unused"})
    elif invalid == "unordered_duplicate":
        data["paths"][0]["checks"].append(data["paths"][0]["checks"][0])
    else:
        data["nodes"][0]["order_id"] = str(uuid4())
    with pytest.raises(ValidationError):
        DomainCatalog.model_validate(data)


def test_fingerprint_preserves_check_order_but_not_node_order():
    catalog = load_domain_catalog()
    reordered = catalog.model_copy(update={"nodes": list(reversed(catalog.nodes)), "paths": list(reversed(catalog.paths))})
    assert fingerprint(catalog) == fingerprint(reordered)
    data = catalog.model_dump()
    data["paths"][0]["checks"].reverse()
    assert fingerprint(catalog) != fingerprint(DomainCatalog.model_validate(data))
    assert catalog.maturity == "demo"


@pytest.mark.asyncio
async def test_disabled_does_not_connect(monkeypatch):
    def forbidden(*_):
        raise AssertionError("关闭图谱不加载 Neo4j 驱动")
    monkeypatch.setattr("app.db.knowledge_graph.importlib.import_module", forbidden)
    async with graph_lifespan(Settings(_env_file=None, graph_enabled=False)) as store:
        assert store is None


@pytest.mark.asyncio
async def test_failed_publish_closes_driver(monkeypatch):
    driver = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr("app.db.knowledge_graph.KnowledgeGraphStore.initialize", AsyncMock())
    monkeypatch.setattr("app.db.knowledge_graph.KnowledgeGraphStore.publish", AsyncMock(side_effect=GraphUnavailableError("失败")))
    monkeypatch.setattr("app.db.knowledge_graph.importlib.import_module", lambda _: SimpleNamespace(
        AsyncGraphDatabase=SimpleNamespace(driver=lambda *a, **k: driver)))
    with pytest.raises(GraphUnavailableError):
        async with graph_lifespan(Settings(_env_file=None, graph_enabled=True, neo4j_password="test-only")):
            pass
    driver.close.assert_awaited_once()


def test_readonly_routes_require_login_and_do_not_fallback_to_local_file():
    app = create_app()
    client = TestClient(app)
    root = "/api/v1/staff/knowledge-graph"
    assert client.get(root + "/catalog").status_code == 401
    app.dependency_overrides[require_staff] = lambda: Principal(id=uuid4(), audience="staff", company_id=uuid4(), display_name="测试客服")
    assert client.get(root + "/catalog").status_code == 503
    app.state.knowledge_graph = SimpleNamespace(read=AsyncMock(return_value=load_domain_catalog()))
    response = client.get(root + "/catalog")
    assert response.status_code == 200 and len(response.json()["paths"]) == 2
    assert client.get(root + "/status").json()["ready"]
    # 上一版文档抽取/审核/手工写入入口彻底退出，而不是隐藏页面后继续允许调用。
    for action in ("extract", "publish", "reset", "withdraw", "sync"):
        assert client.post(root + f"/documents/{uuid4()}/{action}", json={"revision": 1}).status_code == 404
    assert client.put(root + f"/documents/{uuid4()}/draft", json={}).status_code == 404
    app.state.knowledge_graph.read.side_effect = GraphUnavailableError("图数据库断开")
    assert client.get(root + "/catalog").status_code == 503
