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
    """返回回复、会话标识以及本轮持久化消息标识。"""

    conversation_id: UUID
    customer_message_id: UUID
    agent_message_id: UUID
    reply: str
    intent: SupportIntent
    priority: TicketPriority
    requires_human: bool
    reason: str


class MessageResponse(BaseModel):
    """页面恢复历史时使用的只读消息结构。"""

    id: UUID
    role: MessageRole
    content: str
    created_at: datetime


class HealthResponse(BaseModel):
    """健康检查不触发数据库或模型调用。"""

    status: str
    service: str
    version: str