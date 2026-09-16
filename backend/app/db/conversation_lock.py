"""同一会话的检查点更新必须串行；请求幂等键不能代替跨请求的会话锁。"""

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession


class ConversationBusyError(RuntimeError):
    """另一个请求正在推进同一会话，当前请求不排队重放。"""


@asynccontextmanager
async def conversation_lock(
    session: AsyncSession, conversation_id: UUID | None
) -> AsyncIterator[None]:
    if conversation_id is None:
        # 新会话由当前请求独占创建，还不存在可被其他请求引用的 thread。
        yield
        return
    key = int.from_bytes(
        hashlib.sha256(conversation_id.bytes).digest()[:8], "big", signed=True
    )

    async def acquire(connection: AsyncConnection) -> None:
        acquired = await connection.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}
        )
        if not acquired:
            raise ConversationBusyError("当前会话正在处理上一条消息，请稍后再发送")

    bind = session.bind
    if isinstance(bind, AsyncConnection):
        # 集成测试使用外层回滚事务，其结束时一并释放锁。
        await acquire(bind)
        yield
    else:
        assert bind is not None
        # 独立连接只负责锁；业务 Session 中的多次 commit 不会提前释放会话锁。
        async with bind.connect() as connection, connection.begin():
            await acquire(connection)
            yield
