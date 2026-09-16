"""客户工单只公开进度，不返回内部备注、人员邮箱或 Agent 决策信息。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.db.models import TicketStatus


class CustomerTicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    title: str
    description: str
    status: TicketStatus
    updated_at: datetime
    company_id: UUID
    company_name: str = ""
    order_id: UUID | None = None


class ConversationSummary(BaseModel):
    """恢复历史所需的最小会话信息，不携带其他客户数据。"""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    customer_id: UUID
    updated_at: datetime


class CustomerTicketPage(BaseModel):
    items: list[CustomerTicketResponse]
    total: int
