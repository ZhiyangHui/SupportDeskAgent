"""模拟订单输入与客户可见字段，金额用 Decimal 避免浮点误差。"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

OrderStatus = Literal["paid", "shipped", "completed"]


class OrderCreate(BaseModel):
    """只收集演示必需信息，不接受客户 ID、企业 ID 或种子标识。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    product_name: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, le=99999999, max_digits=10, decimal_places=2)
    status: OrderStatus = "paid"
    client_request_id: UUID = Field(default_factory=uuid4)
    received_on: date | None = None

    @model_validator(mode="after")
    def validate_received_on(self) -> "OrderCreate":
        # 模拟签收日期由客户创建样例时填写；旧订单不回填猜测日期。
        if self.received_on and (self.received_on > datetime.now(ZoneInfo("Asia/Shanghai")).date() or self.status != "completed"):
            raise ValueError("只有已完成订单可以填写签收日期，且不能晚于今天")
        return self


class OrderResponse(BaseModel):
    """模型和客户共用安全投影，不携带身份凭证或真实付款信息。"""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    product_name: str
    amount: Decimal
    status: OrderStatus
    created_at: datetime
    received_on: date | None = None


class OrderPage(BaseModel):
    items: list[OrderResponse]
    total: int


class OrderSearch(BaseModel):
    """编号精确匹配优先，否则按商品名关键词查询。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    order_code: str = Field(default="", max_length=40)
    keyword: str = Field(default="", max_length=100)
