"""工单关联订单的只读摘要，不进入客户修改字段白名单。"""

from pydantic import BaseModel, ConfigDict


class TicketOrderSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    product_name: str
