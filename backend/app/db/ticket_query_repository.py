"""客户侧只读工单检索，所有分支强制同时限制企业和客户归属。"""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Ticket
from app.schema.ticket_query import TicketQueryInput, TicketQueryItem, TicketQueryResult


class TicketQueryRepository:
    """仅选择安全列，并使用额外一条记录判断是否需要进一步缩小范围。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self, query: TicketQueryInput, *, company_id: UUID, customer_id: UUID
    ) -> TicketQueryResult:
        statement = select(
            Ticket.code, Ticket.title, Ticket.status, Ticket.updated_at
        ).where(Ticket.company_id == company_id, Ticket.customer_id == customer_id)
        if query.ticket_code:
            statement = statement.where(Ticket.code == query.ticket_code)
        elif query.keyword:
            # autoescape 防止客户输入的 % 和 _ 被误解释成 SQL 通配符。
            statement = statement.where(
                or_(
                    Ticket.title.icontains(query.keyword, autoescape=True),
                    Ticket.description.icontains(query.keyword, autoescape=True),
                )
            )
        rows = (
            await self.session.execute(
                statement.order_by(Ticket.updated_at.desc(), Ticket.id.desc()).limit(6)
            )
        ).all()
        return TicketQueryResult(
            items=[
                TicketQueryItem(
                    code=row.code,
                    title=row.title,
                    status=row.status.value,
                    updated_at=row.updated_at,
                )
                for row in rows[:5]
            ],
            has_more=len(rows) > 5,
        )
