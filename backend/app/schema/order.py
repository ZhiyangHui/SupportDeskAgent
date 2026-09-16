"""模拟订单输入与客户可见字段，金额用 Decimal 避免浮点误差。"""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

OrderStatus = Literal["paid", "shipped", "completed"]


class OrderCreate(BaseModel):
    """只收集演示必需信息，不接受客户 ID、企业 ID 或种子标识。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    product_name: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, le=99999999, max_digits=10, decimal_places=2)
    status: OrderStatus = "paid"
    client_request_id: UUID = Field(default_factory=uuid4)


class OrderResponse(BaseModel):
    """模型和客户共用安全投影，不携带身份凭证或真实付款信息。"""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    product_name: str
    amount: Decimal
    status: OrderStatus
    created_at: datetime


class OrderPage(BaseModel):
    items: list[OrderResponse]
    total: int


class OrderSearch(BaseModel):
    """编号精确匹配优先，否则按商品名关键词查询。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    order_code: str = Field(default="", max_length=40)
    keyword: str = Field(default="", max_length=100)
