from langgraph.graph import MessagesState

from app.agent.schemas import SupportIntent, TicketPriority


class SupportAgentState(MessagesState):
    """LangGraph 单次运行状态，只保存工作流需要的临时信息。"""

    intent: SupportIntent
    priority: TicketPriority
    requires_human: bool
    decision_reason: str
    reply_draft: str
    final_reply: str

