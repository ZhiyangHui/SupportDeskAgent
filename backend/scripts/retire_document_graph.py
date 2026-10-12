"""退役旧文档图谱：默认只核对，--apply 时先导出再删除精确目标。

请停止旧后端再执行。备份含旧资料证据，只写入被 Git 忽略的 storage/graph-backups。
不删除数据卷，不接触知识原文、向量、客户、订单、工单或会话。
"""
import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from neo4j import AsyncGraphDatabase
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

OLD_NODES = "n:SDDocument OR n:SDFact OR n:SDEntity"


def backup(path: Path, data: object) -> None:
    # 独占创建文件，避免覆盖之前的备份；只有写入并落盘后才执行删除。
    import os
    with path.open("x", encoding="utf-8") as file:
        os.chmod(path, 0o600)
        json.dump(data, file, ensure_ascii=False, default=str, indent=2)
        file.flush()
        os.fsync(file.fileno())


async def retire(apply: bool) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    target = Path(__file__).resolve().parents[2] / "storage" / "graph-backups" / f"legacy-data-{uuid4().hex}"
    try:
        async with engine.begin() as connection:
            exists = await connection.scalar(text("SELECT to_regclass('public.knowledge_graph_documents') IS NOT NULL"))
            if exists:
                # 同步期间阻止旧图谱审核表被写入；整个操作还要求旧后端停机。
                await connection.execute(text("LOCK TABLE knowledge_graph_documents IN ACCESS EXCLUSIVE MODE"))
                rows = [dict(r) for r in (await connection.execute(text("SELECT * FROM knowledge_graph_documents"))).mappings()]
            else:
                rows = []
            async with AsyncGraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password)) as driver:
                async def clean(tx):
                    nodes = [dict(r) async for r in await tx.run(f"MATCH (n) WHERE {OLD_NODES} RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS properties")]
                    external = await (await tx.run(f"MATCH (n)-[r]-(m) WHERE ({OLD_NODES}) AND NOT (m:SDDocument OR m:SDFact OR m:SDEntity) RETURN count(r) AS count")).single()
                    if external and external["count"]:
                        raise RuntimeError("旧节点存在指向其他模块的关系，已停止清理，请人工核对")
                    relationships = [dict(r) async for r in await tx.run(f"MATCH (n)-[r]->(m) WHERE {OLD_NODES} RETURN elementId(n) AS source, elementId(m) AS target, type(r) AS type, properties(r) AS properties")]
                    print(f"旧审核记录 {len(rows)} 条，旧图节点 {len(nodes)} 个，旧关系 {len(relationships)} 条")
                    if apply:
                        target.mkdir(parents=True, exist_ok=False, mode=0o700)
                        backup(target / "postgresql.json", rows)
                        backup(target / "neo4j.json", {"nodes": nodes, "relationships": relationships})
                        # 仅删除已导出的节点，不使用 MATCH (n) DETACH DELETE n 一类全库操作。
                        await (await tx.run("MATCH (n) WHERE elementId(n) IN $ids DETACH DELETE n", ids=[n["id"] for n in nodes])).consume()
                # 文件导出是外部副作用，不使用会自动重试事务回调的 execute_write。
                async with driver.session(database=settings.neo4j_database) as session, await session.begin_transaction() as tx:
                    await clean(tx)
                    await tx.commit()
            if apply and exists:
                await connection.execute(text("DELETE FROM knowledge_graph_documents"))
        if apply:
            print(f"旧图谱已清理；备份目录：{target}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="备份后清理旧图谱，默认只检查")
    args = parser.parse_args()
    asyncio.run(retire(args.apply))
