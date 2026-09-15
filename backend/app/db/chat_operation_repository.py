"""请求执行权通过数据库唯一键竞争；这里不提交事务，也不调用模型。"""

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.chat_operation import ChatOperation


class ChatOperationRepository:
    """唯一键冲突表示已有请求，不采用先查后插，避免并发下重复执行。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim(
        self, key: UUID, *, customer_id: UUID, company_id: UUID, fingerprint: str
    ) -> bool:
        statement = (
            insert(ChatOperation)
            .values(
                id=key,
                customer_id=customer_id,
                company_id=company_id,
                fingerprint=fingerprint,
                status="running",
                write_started=False,
            )
            .on_conflict_do_nothing(index_elements=[ChatOperation.id])
            .returning(ChatOperation.id)
        )
        return (await self.session.execute(statement)).scalar_one_or_none() is not None
