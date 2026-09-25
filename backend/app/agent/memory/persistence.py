"""官方 PostgreSQL 记忆资源；连接池由应用生命周期持有，不在每轮聊天中重建。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url

from app.agent.memory.comment_memory import CommentMemory
from app.agent.memory.order_memory import OrderChoice, OrderMemory
from app.agent.memory.ticket_edit_memory import TicketEditMemory
from app.agent.schemas import SupportIntent, TicketCategory, TicketPriority
from app.schema.ticket_comment import TicketCommentResult
from app.schema.ticket_edit import TicketChanges, TicketEditResult


@dataclass
class AgentMemoryResources:
    """短期和长期记忆共用数据库，但使用官方各自的表及接口。"""

    checkpointer: AsyncPostgresSaver
    store: AsyncPostgresStore


_resources: AgentMemoryResources | None = None


def get_memory_resources() -> AgentMemoryResources:
    """不静默降级为内存存储，未初始化意味着应用生命周期配置错误。"""
    if _resources is None:
        raise RuntimeError(
            "Agent PostgreSQL 记忆尚未初始化，请通过应用生命周期启动后端"
        )
    return _resources


def create_memory_serializer() -> JsonPlusSerializer:
    """统一新旧检查点的类型白名单，单独构造便于无数据库验证历史兼容性。"""
    # 只允许业务 State 使用的类型；不启用 pickle 或任意类反序列化。
    return JsonPlusSerializer(
        allowed_msgpack_modules=[
            OrderMemory,
            CommentMemory,
            TicketEditMemory,
            TicketChanges,
            TicketEditResult,
            TicketCommentResult,
            OrderChoice,
            # 仅放行已知旧状态类；配合兼容入口恢复重构前的检查点，不扩大反序列化权限。
            ("app.agent.order_memory", "OrderMemory"),
            ("app.agent.order_memory", "OrderChoice"),
            ("app.agent.comment_memory", "CommentMemory"),
            SupportIntent,
            TicketCategory,
            TicketPriority,
        ]
    )


@asynccontextmanager
async def postgres_memory(database_url: str) -> AsyncIterator[AgentMemoryResources]:
    """按官方要求设置 autocommit 和 dict_row；关闭时归还所有连接。"""
    uri = (
        make_url(database_url)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )
    async with AsyncConnectionPool[AsyncConnection[dict[str, Any]]](
        conninfo=uri,
        min_size=1,
        max_size=8,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        await pool.wait()
        serde = create_memory_serializer()
        saver = AsyncPostgresSaver(pool, serde=serde)
        store = AsyncPostgresStore(pool)
        # setup 包含库维护的迁移。多进程启动通过会话锁串行执行，不复制官方 DDL。
        async with pool.connection() as connection:
            await connection.execute("SELECT pg_advisory_lock(76016301)")
            try:
                await saver.setup()
                await store.setup()
            finally:
                await connection.execute("SELECT pg_advisory_unlock(76016301)")
        yield AgentMemoryResources(saver, store)


@asynccontextmanager
async def agent_memory_lifespan(database_url: str) -> AsyncIterator[None]:
    """安装进程级资源；图缓存不能跨越连接池的生命周期。"""
    global _resources
    from app.agent.factory import get_support_graph

    async with postgres_memory(database_url) as resources:
        _resources = resources
        get_support_graph.cache_clear()
        try:
            yield
        finally:
            get_support_graph.cache_clear()
            _resources = None
