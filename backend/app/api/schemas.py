from pydantic import BaseModel, Field

from app.agent.schemas import SupportIntent, TicketPriority


class ChatRequest(BaseModel):
    """最小聊天请求，后续会增加会话编号和客户身份。"""

    message: str = Field(min_length=1, max_length=4000, description="客户本轮输入")


class ChatResponse(BaseModel):
    """返回回复的同时暴露可展示的 Agent 判断结果。"""

    reply: str
    intent: SupportIntent
    priority: TicketPriority
    requires_human: bool
    reason: str


class HealthResponse(BaseModel):
    """健康检查响应不触发模型调用，只确认 API 进程可用。"""

    status: str
    service: str
    version: str

