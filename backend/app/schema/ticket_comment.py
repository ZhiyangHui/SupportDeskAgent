"""客户补充工单的输入与结果，不允许模型提供客户、企业或操作者身份。"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TicketCommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    ticket_code: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=4000)


class TicketCommentResult(BaseModel):
    """成功表示备注和请求回执已经同事务提交，而非模型预测。"""

    success: bool
    message: str
    ticket_code: str | None = None
    ticket_id: UUID | None = None
    activity_id: UUID | None = None
