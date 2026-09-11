from uuid import UUID

from langgraph.graph import MessagesState

from app.agent.schemas import SupportIntent, TicketCategory, TicketPriority


class SupportAgentState(MessagesState):
    """LangGraph 单次运行状态，只保存工作流需要的临时信息。"""

    intent: SupportIntent
    priority: TicketPriority
    requires_human: bool
    should_create_ticket: bool
    needs_ticket_details: bool
    ticket_title: str | None
    ticket_description: str | None
    ticket_category: TicketCategory
    created_ticket_id: UUID | None
    created_ticket_code: str | None
    decision_reason: str
    reply_draft: str
    final_reply: str
