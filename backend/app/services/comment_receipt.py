"""核对追加备注的持久化回执，供聊天错误反馈和企业运行记录共用。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.chat_operation import ChatOperation
from app.db.models import Ticket, TicketActivity


async def get_commented_ticket(
    session: AsyncSession, operation: ChatOperation
) -> Ticket | None:
    """只认可同事务保存的活动记录，并再次核对客户和企业，不凭 write_started 推测成功。"""
    if not operation.comment_activity_id:
        return None
    activity = await session.get(TicketActivity, operation.comment_activity_id)
    ticket = await session.get(Ticket, activity.ticket_id) if activity else None
    if (
        ticket
        and ticket.customer_id == operation.customer_id
        and ticket.company_id == operation.company_id
    ):
        return ticket
    raise RuntimeError("补充工单回执不完整或归属不一致")


async def get_updated_ticket(session: AsyncSession, operation: ChatOperation) -> Ticket | None:
    """修改有独立回执；旧补充回执保持原含义，不重新解释历史操作。"""
    if not operation.update_activity_id:
        return None
    activity = await session.get(TicketActivity, operation.update_activity_id)
    ticket = await session.get(Ticket, activity.ticket_id) if activity else None
    if ticket and ticket.customer_id == operation.customer_id and ticket.company_id == operation.company_id:
        return ticket
    raise RuntimeError("修改工单回执不完整")
