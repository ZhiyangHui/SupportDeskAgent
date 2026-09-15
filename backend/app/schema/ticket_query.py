"""工单查询的输入边界和客户可见结果，禁止直接序列化完整 ORM 对象。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TicketQueryInput(BaseModel):
    """编号优先精确查询；没有编号时按关键词查找，为空则返回最近工单。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    ticket_code: str = Field(default="", max_length=100)
    keyword: str = Field(default="", max_length=100)


class TicketQueryItem(BaseModel):
    """只返回进度所需字段，不包含内部备注、联系方式或客服身份。"""

    code: str
    title: str
    status: str
    updated_at: datetime


class TicketQueryResult(BaseModel):
    """最多五条候选项；has_more 提醒模型请客户缩小范围。"""

    items: list[TicketQueryItem]
    has_more: bool = False
