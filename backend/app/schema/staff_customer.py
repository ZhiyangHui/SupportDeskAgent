"""企业客户列表仅显示已与本企业建立咨询关系的客户。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class StaffCustomerResponse(BaseModel):
    id: UUID
    display_name: str
    conversation_count: int
    updated_at: datetime


class StaffConversationResponse(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str
    updated_at: datetime
