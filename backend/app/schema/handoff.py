"""接管协议仅接受操作和消息，身份、企业归属都从认证获取。"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HandoffState(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status: str
    handoff_staff_id: UUID | None
    handoff_requested_at: datetime | None = None
    handoff_reason: str = ""


class HandoffQueueItem(BaseModel):
    conversation_id: UUID
    customer_name: str
    requested_at: datetime | None
    reason: str
    status: str


class HandoffQueuePage(BaseModel):
    items: list[HandoffQueueItem]
    total: int


class HandoffAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["takeover", "resume"]


class StaffReply(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=4000)
    client_request_id: UUID
