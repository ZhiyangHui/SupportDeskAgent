"""客户查询总是包含登录客户 ID，企业筛选不能替代客户归属。"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, Conversation, Ticket


class CustomerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_tickets(
        self, customer_id: UUID, offset: int, limit: int
    ) -> tuple[list[tuple[Ticket, str]], int]:
        base = (
            select(Ticket, Company.name)
            .join(Company, Ticket.company_id == Company.id)
            .where(Ticket.customer_id == customer_id)
        )
        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        rows = await self.session.execute(
            base.order_by(Ticket.updated_at.desc(), Ticket.id)
            .offset(offset)
            .limit(limit)
        )
        return [(row[0], row[1]) for row in rows.all()], total or 0

    async def list_conversations(
        self, customer_id: UUID, company_id: UUID, offset: int, limit: int
    ) -> list[Conversation]:
        return list(
            (
                await self.session.scalars(
                    select(Conversation)
                    .where(
                        Conversation.customer_id == customer_id,
                        Conversation.company_id == company_id,
                    )
                    .order_by(Conversation.updated_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
