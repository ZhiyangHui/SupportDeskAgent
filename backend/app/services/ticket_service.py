from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversation_repository import ConversationRepository
from app.db.models import (
    Ticket,
    TicketActivityType,
    TicketPriorityValue,
    TicketSource,
    TicketStatus,
)
from app.db.ticket_repository import TicketPage, TicketRepository


class InvalidTicketTransitionError(ValueError):
    """工单状态不允许按请求方式跳转时抛出。"""


# 状态机明确约束业务流转，前端按钮只改善体验，不能代替后端校验。
ALLOWED_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.OPEN: {TicketStatus.IN_PROGRESS, TicketStatus.CLOSED},
    TicketStatus.IN_PROGRESS: {
        TicketStatus.WAITING_CUSTOMER,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.WAITING_CUSTOMER: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.RESOLVED: {TicketStatus.IN_PROGRESS, TicketStatus.CLOSED},
    TicketStatus.CLOSED: set(),
}


class TicketService:
    """执行工单领域规则、事务提交和审计记录，所有修改必须经过本层。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = TicketRepository(session)
        self.conversation_repository = ConversationRepository(session)

    async def create_ticket(
        self,
        *,
        title: str,
        description: str,
        category: str,
        priority: TicketPriorityValue,
        source: TicketSource,
        operator_name: str,
        conversation_id: UUID | None,
        customer_name: str | None,
        customer_email: str | None,
    ) -> Ticket:
        """创建工单和首条审计记录；任意一步失败时整体回滚。"""

        try:
            if conversation_id is not None:
                await self.conversation_repository.get_conversation(conversation_id)

            now = datetime.now(UTC)
            # 日期便于人工识别，UUID 片段降低并发创建时的编号冲突概率。
            code = f"TK-{now:%Y%m%d}-{uuid4().hex[:8].upper()}"
            ticket = Ticket(
                code=code,
                conversation_id=conversation_id,
                title=title.strip(),
                description=description.strip(),
                category=category.strip() or "general",
                priority=priority,
                source=source,
                customer_name=customer_name.strip() if customer_name else None,
                customer_email=customer_email.strip() if customer_email else None,
            )
            await self.repository.add_ticket(ticket)
            await self.repository.add_activity(
                ticket_id=ticket.id,
                activity_type=TicketActivityType.CREATED,
                operator_name=operator_name,
                content="创建工单",
                to_value=ticket.status.value,
            )
            await self.session.commit()
            return await self.repository.get_ticket(ticket.id, with_activities=True)
        except Exception:
            await self.session.rollback()
            raise

    async def update_ticket(
        self,
        ticket_id: UUID,
        *,
        ticket_status: TicketStatus | None,
        priority: TicketPriorityValue | None,
        assignee_name: str | None,
        update_assignee: bool,
        operator_name: str,
    ) -> Ticket:
        """在一个事务内更新工单当前值，并为每项变化写入独立审计记录。"""

        try:
            ticket = await self.repository.get_ticket(ticket_id, for_update=True)
            changed = False

            if ticket_status is not None and ticket_status != ticket.status:
                if ticket_status not in ALLOWED_TRANSITIONS[ticket.status]:
                    raise InvalidTicketTransitionError(
                        f"不允许从 {ticket.status.value} 转换到 {ticket_status.value}"
                    )
                previous = ticket.status
                ticket.status = ticket_status
                await self.repository.add_activity(
                    ticket_id=ticket.id,
                    activity_type=TicketActivityType.STATUS_CHANGED,
                    operator_name=operator_name,
                    from_value=previous.value,
                    to_value=ticket_status.value,
                )
                changed = True

            if priority is not None and priority != ticket.priority:
                previous_priority = ticket.priority
                ticket.priority = priority
                await self.repository.add_activity(
                    ticket_id=ticket.id,
                    activity_type=TicketActivityType.PRIORITY_CHANGED,
                    operator_name=operator_name,
                    from_value=previous_priority.value,
                    to_value=priority.value,
                )
                changed = True

            if update_assignee:
                normalized_assignee = assignee_name.strip() if assignee_name else None
                if normalized_assignee != ticket.assignee_name:
                    previous_assignee = ticket.assignee_name
                    ticket.assignee_name = normalized_assignee
                    await self.repository.add_activity(
                        ticket_id=ticket.id,
                        activity_type=TicketActivityType.ASSIGNED,
                        operator_name=operator_name,
                        from_value=previous_assignee,
                        to_value=normalized_assignee,
                    )
                    changed = True

            if changed:
                ticket.version += 1
                ticket.updated_at = datetime.now(UTC)
            await self.session.commit()
            return await self.repository.get_ticket(ticket.id, with_activities=True)
        except Exception:
            await self.session.rollback()
            raise

    async def add_note(self, ticket_id: UUID, *, content: str, operator_name: str) -> Ticket:
        """追加处理备注，不允许覆盖既有审计记录。"""

        try:
            ticket = await self.repository.get_ticket(ticket_id, for_update=True)
            await self.repository.add_activity(
                ticket_id=ticket.id,
                activity_type=TicketActivityType.NOTE_ADDED,
                operator_name=operator_name,
                content=content.strip(),
            )
            ticket.version += 1
            ticket.updated_at = datetime.now(UTC)
            await self.session.commit()
            return await self.repository.get_ticket(ticket.id, with_activities=True)
        except Exception:
            await self.session.rollback()
            raise

    async def get_ticket(self, ticket_id: UUID) -> Ticket:
        return await self.repository.get_ticket(ticket_id, with_activities=True)

    async def list_tickets(
        self,
        *,
        ticket_status: TicketStatus | None,
        priority: TicketPriorityValue | None,
        keyword: str | None,
        offset: int,
        limit: int,
    ) -> TicketPage:
        return await self.repository.list_tickets(
            ticket_status=ticket_status,
            priority=priority,
            keyword=keyword,
            offset=offset,
            limit=limit,
        )

    async def get_statistics(self) -> dict[str, int]:
        return await self.repository.get_statistics()
