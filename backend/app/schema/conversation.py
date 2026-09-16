"""会话及健康检查接口的数据协议，集中定义输入校验与客户端可见的响应字段。"""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from app.agent.schemas import SupportIntent, TicketPriority
from app.db.models import MessageRole


class ChatRequest(BaseModel):
    """首次请求不传会话 ID，后续请求使用响应中的 ID 延续上下文。"""

    message: str = Field(min_length=1, max_length=4000, description="客户本轮输入")
    conversation_id: UUID | None = None
    company_id: UUID
    # 客户端对同一逻辑请求复用此键；兼容旧客户端时自动生成，但旧客户端不具备跨请求幂等。
    client_request_id: UUID = Field(default_factory=uuid4)


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
    agent_run_id: UUID
    queried_tickets: bool = False
    executed_tool: Literal["create_support_ticket", "query_support_tickets", "query_my_orders", "create_order_ticket"] | None = None

    @field_validator("executed_tool", mode="before")
    @classmethod
    def normalize_legacy_empty_tool(cls, value: object) -> object:
        """兼容修复前已保存的成功回执，使同键重试直接恢复回复，不重新执行工具。"""
        # 仅兼容已知旧值；未知工具名称仍由枚举拒绝，避免前后端协议再次悄悄分歧。
        return None if value == "" else value


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
    ticket_code: str | None = None


class HealthResponse(BaseModel):
    """健康检查不触发数据库或模型调用。"""

    status: str
    service: str
    version: str
