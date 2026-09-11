from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.agent.schemas import SupportIntent, TicketPriority
from app.db.models import MessageRole


class ChatRequest(BaseModel):
    """首次请求不传会话 ID，后续请求使用响应中的 ID 延续上下文。"""

    message: str = Field(min_length=1, max_length=4000, description="客户本轮输入")
    conversation_id: UUID | None = None


class ChatResponse(BaseModel):
    """返回回复、会话标识以及 Agent 本轮可能创建的工单信息。"""

    conversation_id: UUID
    customer_message_id: UUID
    agent_message_id: UUID
    reply: str
    intent: SupportIntent
    priority: TicketPriority
    requires_human: bool
    reason: str
    created_ticket_id: UUID | None = None
    created_ticket_code: str | None = None


class MessageResponse(BaseModel):
    """页面恢复历史时使用的只读消息结构，包括已完成的 Tool Call 摘要。"""

    id: UUID
    role: MessageRole
    content: str
    created_at: datetime
    tool_call: "MessageToolCallResponse | None" = None


class MessageToolCallResponse(BaseModel):
    """只暴露页面展示需要的安全结果，不返回 Tool 的内部运行上下文。"""

    name: str
    status: str
    ticket_code: str


class HealthResponse(BaseModel):
    """健康检查不触发数据库或模型调用。"""

    status: str
    service: str
    version: str
