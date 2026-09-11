from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.models import Ticket, TicketPriorityValue, TicketStatus
from app.services.ticket_service import InvalidTicketTransitionError, TicketService


def build_ticket(*, status: TicketStatus = TicketStatus.OPEN) -> Ticket:
    """构造不依赖数据库的工单实体，让状态机测试保持快速且可重复。"""

    return Ticket(
        id=uuid4(),
        code="TK-TEST-001",
        title="企业账号无法登录",
        description="客户登录时提示账号已锁定",
        category="account",
        status=status,
        priority=TicketPriorityValue.HIGH,
        version=1,
    )


@pytest.mark.asyncio
async def test_ticket_status_transition_writes_audit_record() -> None:
    """合法状态变化必须同时更新当前快照与审计记录。"""

    session = AsyncMock()
    service = TicketService(session)
    ticket = build_ticket()
    service.repository.get_ticket = AsyncMock(return_value=ticket)
    service.repository.add_activity = AsyncMock()

    result = await service.update_ticket(
        ticket.id,
        ticket_status=TicketStatus.IN_PROGRESS,
        priority=None,
        assignee_name=None,
        update_assignee=False,
        operator_name="测试客服",
    )

    assert result.status == TicketStatus.IN_PROGRESS
    assert result.version == 2
    service.repository.add_activity.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_closed_ticket_cannot_be_reopened() -> None:
    """已关闭工单属于终态，非法重开必须回滚且不能留下半条审计记录。"""

    session = AsyncMock()
    service = TicketService(session)
    ticket = build_ticket(status=TicketStatus.CLOSED)
    service.repository.get_ticket = AsyncMock(return_value=ticket)
    service.repository.add_activity = AsyncMock()

    with pytest.raises(InvalidTicketTransitionError):
        await service.update_ticket(
            ticket.id,
            ticket_status=TicketStatus.IN_PROGRESS,
            priority=None,
            assignee_name=None,
            update_assignee=False,
            operator_name="测试客服",
        )

    service.repository.add_activity.assert_not_awaited()
    session.rollback.assert_awaited_once()
