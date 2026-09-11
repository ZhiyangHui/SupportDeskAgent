from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.db.models import (
    TicketActivityType,
    TicketPriorityValue,
    TicketSource,
    TicketStatus,
)


class TicketCreateRequest(BaseModel):
    """人工创建或会话转单的输入，业务生成的编号和状态不允许由客户端指定。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=2, max_length=10000)
    category: str = Field(default="general", min_length=1, max_length=50)
    priority: TicketPriorityValue = TicketPriorityValue.MEDIUM
    conversation_id: UUID | None = None
    customer_name: str | None = Field(default=None, max_length=100)
    customer_email: EmailStr | None = None
    operator_name: str = Field(default="客服专员", min_length=1, max_length=100)


class TicketUpdateRequest(BaseModel):
    """工单可变字段；赋值为 null 的 assignee_name 表示取消指派。"""

    model_config = ConfigDict(extra="forbid")

    status: TicketStatus | None = None
    priority: TicketPriorityValue | None = None
    assignee_name: str | None = Field(default=None, max_length=100)
    operator_name: str = Field(default="客服专员", min_length=1, max_length=100)

    @model_validator(mode="after")
    def ensure_change_exists(self) -> "TicketUpdateRequest":
        mutable_fields = {"status", "priority", "assignee_name"}
        if not self.model_fields_set.intersection(mutable_fields):
            raise ValueError("至少需要提交一个工单变更字段")
        return self


class TicketNoteRequest(BaseModel):
    """处理备注独立建模，避免备注被当成工单描述覆盖。"""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=5000)
    operator_name: str = Field(default="客服专员", min_length=1, max_length=100)


class TicketActivityResponse(BaseModel):
    """供详情时间线展示的不可变审计记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    activity_type: TicketActivityType
    operator_name: str
    content: str | None
    from_value: str | None
    to_value: str | None
    created_at: datetime


class TicketResponse(BaseModel):
    """工单详情响应包含当前快照和完整审计时间线。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    conversation_id: UUID | None
    title: str
    description: str
    category: str
    status: TicketStatus
    priority: TicketPriorityValue
    source: TicketSource
    customer_name: str | None
    customer_email: str | None
    assignee_name: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    # default_factory 为每个响应创建独立列表，避免可变默认值被多个对象意外共享。
    activities: list[TicketActivityResponse] = Field(default_factory=list)


class TicketSummaryResponse(BaseModel):
    """列表只返回决策所需摘要，避免为每行加载完整审计记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    title: str
    category: str
    status: TicketStatus
    priority: TicketPriorityValue
    source: TicketSource
    customer_name: str | None
    assignee_name: str | None
    created_at: datetime
    updated_at: datetime


class TicketListResponse(BaseModel):
    items: list[TicketSummaryResponse]
    total: int
    offset: int
    limit: int


class TicketStatisticsResponse(BaseModel):
    total: int
    open: int
    in_progress: int
    waiting_customer: int
    resolved: int
    closed: int
