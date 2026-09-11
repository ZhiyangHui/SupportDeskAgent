from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Ticket,
    TicketActivity,
    TicketActivityType,
    TicketPriorityValue,
    TicketStatus,
)


class TicketNotFoundError(LookupError):
    """请求的工单不存在时抛出，由 API 层稳定转换为 404。"""


@dataclass(frozen=True, slots=True)
class TicketPage:
    """工单分页查询结果；总数与当前页数据来自同一组筛选条件。"""

    items: list[Ticket]
    total: int


class TicketRepository:
    """封装工单相关 SQL，避免查询细节泄漏到 Service 和路由。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_ticket(self, ticket: Ticket) -> Ticket:
        self.session.add(ticket)
        await self.session.flush()
        return ticket

    async def get_ticket(
        self,
        ticket_id: UUID,
        *,
        with_activities: bool = False,
        for_update: bool = False,
    ) -> Ticket:
        statement = select(Ticket).where(Ticket.id == ticket_id)
        if with_activities:
            # selectinload 通过独立查询加载审计记录，避免异步环境中触发隐式懒加载。
            statement = statement.options(selectinload(Ticket.activities))
        if for_update:
            # 修改前锁定主记录，使两个客服同时操作时按事务顺序执行，避免状态和版本互相覆盖。
            statement = statement.with_for_update()
        ticket = await self.session.scalar(statement)
        if ticket is None:
            raise TicketNotFoundError(f"工单 {ticket_id} 不存在")
        return ticket

    async def list_tickets(
        self,
        *,
        ticket_status: TicketStatus | None,
        priority: TicketPriorityValue | None,
        keyword: str | None,
        offset: int,
        limit: int,
    ) -> TicketPage:
        filters = []
        if ticket_status is not None:
            filters.append(Ticket.status == ticket_status)
        if priority is not None:
            filters.append(Ticket.priority == priority)
        if keyword:
            pattern = f"%{keyword.strip()}%"
            filters.append(
                or_(
                    Ticket.code.ilike(pattern),
                    Ticket.title.ilike(pattern),
                    Ticket.customer_name.ilike(pattern),
                )
            )

        base: Select[tuple[Ticket]] = select(Ticket).where(*filters)
        total_statement = select(func.count()).select_from(Ticket).where(*filters)
        total = int(await self.session.scalar(total_statement) or 0)
        items = list(
            (
                await self.session.scalars(
                    base.order_by(Ticket.updated_at.desc(), Ticket.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        return TicketPage(items=items, total=total)

    async def add_activity(
        self,
        *,
        ticket_id: UUID,
        activity_type: TicketActivityType,
        operator_name: str,
        content: str | None = None,
        from_value: str | None = None,
        to_value: str | None = None,
    ) -> TicketActivity:
        activity = TicketActivity(
            ticket_id=ticket_id,
            activity_type=activity_type,
            operator_name=operator_name,
            content=content,
            from_value=from_value,
            to_value=to_value,
        )
        self.session.add(activity)
        await self.session.flush()
        return activity

    async def get_statistics(self) -> dict[str, int]:
        """在数据库端聚合状态数量，避免把全部工单加载到应用内存。"""

        result = await self.session.execute(
            select(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status)
        )
        counts = {status.value: int(count) for status, count in result.all()}
        return {
            "total": sum(counts.values()),
            "open": counts.get(TicketStatus.OPEN.value, 0),
            "in_progress": counts.get(TicketStatus.IN_PROGRESS.value, 0),
            "waiting_customer": counts.get(TicketStatus.WAITING_CUSTOMER.value, 0),
            "resolved": counts.get(TicketStatus.RESOLVED.value, 0),
            "closed": counts.get(TicketStatus.CLOSED.value, 0),
        }
