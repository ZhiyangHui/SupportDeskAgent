from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

# pool_pre_ping 会在取出连接时检测失效连接，减少数据库重启后的首次请求错误。
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """为每个 HTTP 请求提供独立 Session，事务提交由 Service 明确控制。"""

    async with async_session_factory() as session:
        yield session