"""稳定领域知识图存储：不可变版本、固定路径关系；不复制业务数据或文档片段。"""
import asyncio
import hashlib
import importlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.config import Settings
from app.knowledge.domain_catalog import load_domain_catalog
from app.schema.knowledge_graph import DomainCatalog

# 所有图关系由程序固定，内容只走参数；绝不接受模型生成的 Cypher。
ROLES = {
    "CATEGORY": "category", "SYMPTOM": "symptom", "POSSIBLE_CAUSE": "cause",
    "CHECK": "checks", "SOLUTION": "solution", "REQUIRES": "requires", "EXCLUDES": "excludes",
}
LIST_FIELDS = {"checks", "requires", "excludes"}


class GraphUnavailableError(RuntimeError):
    """连接错误只返回稳定说明，防止连接参数和秘密进入响应。"""


class GraphRevisionConflict(ValueError):
    """同一版本不可修改内容；旧版本不可覆盖新知识。"""


def fingerprint(catalog: DomainCatalog) -> str:
    data = catalog.model_dump(mode="json")
    # 节点和路径排列不影响含义，但检查步骤的顺序必须保留。
    data["nodes"] = sorted(data["nodes"], key=lambda item: item["id"])
    data["paths"] = sorted(data["paths"], key=lambda item: item["id"])
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class KnowledgeGraphStore:
    def __init__(self, driver: Any, database: str, timeout: float = 10):
        self.driver, self.database, self.timeout = driver, database, timeout

    async def initialize(self) -> None:
        async with asyncio.timeout(self.timeout):
            await self.driver.verify_connectivity()
            await self.driver.execute_query(
                "CREATE CONSTRAINT domain_catalog_id IF NOT EXISTS FOR (n:DomainCatalog) REQUIRE n.id IS UNIQUE",
                database_=self.database)
            for label in ("DomainRelease", "DomainConcept", "DomainPath"):
                fields = "(n.catalog, n.version)" if label == "DomainRelease" else "(n.catalog, n.version, n.id)"
                await self.driver.execute_query(
                    f"CREATE CONSTRAINT {label.lower()}_identity IF NOT EXISTS FOR (n:{label}) REQUIRE {fields} IS UNIQUE",
                    database_=self.database)

    async def publish(self, catalog: DomainCatalog) -> None:
        """完整版本事务发布；重启时同内容不重复写入，失败保留上一版本。"""
        catalog = DomainCatalog.model_validate(catalog.model_dump())
        data = catalog.model_dump(mode="json")
        scope = {"catalog": catalog.id, "version": catalog.version, "fingerprint": fingerprint(catalog)}
        paths = []
        for path in data["paths"]:
            paths.append({key: value for key, value in path.items() if key in {"id", "explanation", "escalation"}})

        async def write(tx: Any) -> None:
            current = await (await tx.run("""
                MERGE (c:DomainCatalog {id: $catalog})
                SET c.lock_version = coalesce(c.lock_version, 0) + 1
                RETURN c.active_version AS version, c.fingerprint AS fingerprint
            """, **scope)).single()
            if current and current["version"] is not None:
                if current["version"] > catalog.version or (
                    current["version"] == catalog.version and current["fingerprint"] != scope["fingerprint"]
                ):
                    raise GraphRevisionConflict("知识版本冲突：修改内容必须递增版本，不能用旧版本覆盖")
                if current["version"] == catalog.version:
                    return
            metadata = {key: data[key] for key in ("title", "maturity", "provenance")}
            await (await tx.run("""
                MATCH (c:DomainCatalog {id: $catalog})
                CREATE (v:DomainRelease {catalog: $catalog, version: $version})
                SET v += $metadata, v.fingerprint = $fingerprint
                MERGE (c)-[:HAS_RELEASE]->(v)
                WITH v UNWIND $nodes AS node
                CREATE (n:DomainConcept {catalog: $catalog, version: $version})
                SET n += node
                CREATE (v)-[:HAS_CONCEPT]->(n)
            """, **scope, metadata=metadata, nodes=data["nodes"])).consume()
            await (await tx.run("""
                MATCH (v:DomainRelease {catalog: $catalog, version: $version})
                UNWIND $paths AS path
                CREATE (p:DomainPath {catalog: $catalog, version: $version})
                SET p += path
                CREATE (v)-[:HAS_PATH]->(p)
            """, **scope, paths=paths)).consume()
            for relation, field in ROLES.items():
                links: list[dict[str, Any]] = []
                for path in data["paths"]:
                    ids = path[field] if field in LIST_FIELDS else [path[field]]
                    links.extend({"path": path["id"], "node": key, "position": index} for index, key in enumerate(ids))
                await (await tx.run(f"""
                    UNWIND $links AS link
                    MATCH (p:DomainPath {{catalog: $catalog, version: $version, id: link.path}})
                    MATCH (n:DomainConcept {{catalog: $catalog, version: $version, id: link.node}})
                    CREATE (p)-[:{relation} {{position: link.position}}]->(n)
                """, **scope, links=links)).consume()
            # 最后才切换活动版本。老版本保留，读请求固定读取一个不可变版本，不会混合两版路径。
            await (await tx.run("""
                MATCH (c:DomainCatalog {id: $catalog})
                SET c.active_version = $version, c.fingerprint = $fingerprint
            """, **scope)).consume()

        try:
            async with asyncio.timeout(self.timeout):
                async with self.driver.session(database=self.database) as session:
                    await session.execute_write(write)
        except GraphRevisionConflict:
            raise
        except Exception as exc:
            raise GraphUnavailableError("领域知识同步未确认完成，请按同一知识版本重新启动核对") from exc

    async def read(self, catalog_id: str) -> DomainCatalog:
        """从真实图关系还原完整排查路径；不拿本地文件冒充图数据库查询成功。"""
        async def read_tx(tx: Any) -> DomainCatalog:
            header = await (await tx.run("""
                MATCH (c:DomainCatalog {id: $catalog})
                MATCH (v:DomainRelease {catalog: $catalog, version: c.active_version})
                RETURN properties(v) AS metadata
            """, catalog=catalog_id)).single()
            if not header:
                raise GraphUnavailableError("领域知识尚未发布，请重启后端完成知识包同步")
            metadata = dict(header["metadata"])
            version = metadata["version"]
            nodes = [dict(r["node"]) async for r in await tx.run("""
                MATCH (n:DomainConcept {catalog: $catalog, version: $version})
                RETURN n { .id, .kind, .name, .description } AS node ORDER BY n.id
            """, catalog=catalog_id, version=version)]
            paths = []
            records = await tx.run("""
                MATCH (p:DomainPath {catalog: $catalog, version: $version})-[r]->(n:DomainConcept {catalog: $catalog, version: $version})
                WITH p, r, n ORDER BY r.position
                RETURN p { .id, .explanation, .escalation } AS path,
                       collect({role: type(r), node: n.id}) AS links ORDER BY path.id
            """, catalog=catalog_id, version=version)
            async for record in records:
                path = dict(record["path"])
                path.update({field: [] for field in LIST_FIELDS})
                for link in record["links"]:
                    field = ROLES.get(link["role"])
                    if field is None:
                        raise GraphUnavailableError("图谱出现未知关系，请核对知识版本")
                    if field in LIST_FIELDS:
                        path[field].append(link["node"])
                    elif field in path:
                        raise GraphUnavailableError("图谱路径存在重复端点，请核对知识版本")
                    else:
                        path[field] = link["node"]
                paths.append(path)
            result = DomainCatalog.model_validate({"id": catalog_id, "version": version,
                **{key: metadata[key] for key in ("title", "maturity", "provenance")}, "nodes": nodes, "paths": paths})
            if fingerprint(result) != metadata["fingerprint"]:
                raise GraphUnavailableError("图谱内容与已发布版本不一致，请核对图数据库")
            return result
        try:
            async with asyncio.timeout(self.timeout):
                async with self.driver.session(database=self.database) as session:
                    return await session.execute_read(read_tx)
        except GraphUnavailableError:
            raise
        except Exception as exc:
            raise GraphUnavailableError("领域图谱查询失败，请检查 Neo4j 服务") from exc


@asynccontextmanager
async def graph_lifespan(settings: Settings) -> AsyncIterator[KnowledgeGraphStore | None]:
    """应用启用图谱后自动加载经过版本管理的后端知识包，不调用模型或读取业务主库。"""
    if not settings.graph_enabled:
        yield None
        return
    if not settings.neo4j_password or not settings.neo4j_username or not settings.neo4j_database:
        raise GraphUnavailableError("启用图谱前请填写 Neo4j 账号、密码和数据库")
    catalog = load_domain_catalog()
    try:
        module = importlib.import_module("neo4j")
    except ImportError as exc:
        raise GraphUnavailableError("缺少 Neo4j 驱动，请自行安装已有 requirements.txt 中的依赖") from exc
    driver = module.AsyncGraphDatabase.driver(settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
        connection_timeout=settings.graph_timeout_seconds,
        connection_acquisition_timeout=settings.graph_timeout_seconds,
        max_transaction_retry_time=0, max_connection_pool_size=10)
    try:
        store = KnowledgeGraphStore(driver, settings.neo4j_database, settings.graph_timeout_seconds)
        try:
            await store.initialize()
        except Exception as exc:
            raise GraphUnavailableError("Neo4j 初始化失败，请检查服务、账号及建约束权限") from exc
        await store.publish(catalog)
        yield store
    finally:
        await driver.close()
