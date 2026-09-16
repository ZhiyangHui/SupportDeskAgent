from uuid import UUID

from langgraph.graph import MessagesState

from app.agent.order_memory import OrderChoice, OrderMemory
from app.agent.schemas import SupportIntent, TicketCategory, TicketPriority


class SupportAgentState(MessagesState):
    """Checkpointer 保存的会话状态；每轮临时字段在入口重置，业务实体留在业务表。"""

    intent: SupportIntent
    priority: TicketPriority
    requires_human: bool
    should_create_ticket: bool
    should_query_ticket: bool
    needs_order_lookup: bool
    # 从上一轮成功回复的结构化记录恢复，只用于查询定位，不替代本轮权限核验。
    selected_order_code: str
    order_memory: OrderMemory
    use_order_workflow: bool
    order_candidates: list[OrderChoice]
    available_order_ids: list[str]
    order_options: list[str]
    order_rounds: int
    query_rounds: int
    query_deadline: float
    # 未调用工具必须为 None，与接口 JSON null 一致，不能用空字符串充当工具名。
    executed_tool: str | None
    needs_ticket_details: bool
    ticket_title: str | None
    ticket_description: str | None
    ticket_category: TicketCategory
    created_ticket_id: UUID | None
    created_ticket_code: str | None
    decision_reason: str
    reply_draft: str
    final_reply: str
    customer_preferences: dict[str, str]
