"""Agent 运行记录的只读接口协议，与 Graph 内部运行状态分开维护。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.db.models import AgentRunStatus


class AgentRunResponse(BaseModel):
    """运行详情只暴露诊断元数据，不返回客户原始消息和密钥。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_id: str
    conversation_id: UUID | None
    ticket_id: UUID | None
    status: AgentRunStatus
    model_name: str
    intent: str | None
    priority: str | None
    requires_human: bool | None
    decision_reason: str | None
    tool_name: str | None
    ticket_code: str | None
    duration_ms: int | None
    error_type: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class AgentRunListResponse(BaseModel):
    items: list[AgentRunResponse]
    total: int
    offset: int
    limit: int


class AgentRunStatisticsResponse(BaseModel):
    total: int
    running: int
    succeeded: int
    failed: int
    tool_calls: int
    average_duration_ms: float
