"""客户可修改字段白名单；与员工侧状态、优先级和指派接口严格分开。"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schema.ticket_order import TicketOrderSummary


class TicketChanges(BaseModel):
    """None 表示本轮未修改；售后诉求、影响说明允许明确清空为字符串空值。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, min_length=2, max_length=10000)
    desired_resolution: str | None = Field(default=None, max_length=2000)
    impact_note: str | None = Field(default=None, max_length=2000)

    def patch(self) -> dict[str, str]:
        return self.model_dump(exclude_none=True)


class TicketEditInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    ticket_code: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)
    changes: TicketChanges

    @model_validator(mode="after")
    def require_changes(self) -> "TicketEditInput":
        if not self.changes.patch():
            raise ValueError("至少需要修改一个允许字段")
        return self


class CustomerTicketSnapshot(BaseModel):
    """查库后的只读快照，只携带展示与并发核对所需字段。"""

    model_config = ConfigDict(from_attributes=True)
    code: str
    version: int
    status: str
    title: str
    description: str
    desired_resolution: str
    impact_note: str
    order: TicketOrderSummary | None = None


class TicketEditResult(BaseModel):
    success: bool
    message: str
    changed: bool = False
    conflict: bool = False
    ticket_id: UUID | None = None
    ticket_code: str | None = None
    activity_id: UUID | None = None


EDIT_LABELS = {
    "title": "问题标题",
    "description": "问题描述",
    "desired_resolution": "售后诉求",
    "impact_note": "影响／紧急情况说明",
}
