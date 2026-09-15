"""持久化聊天请求幂等状态与建单回执，跨进程重试也不会重复派发同一请求。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChatOperation(Base):
    """工单回执与工单在同一事务提交；请求响应可以随后独立保存。"""

    __tablename__ = "chat_operations"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer_accounts.id"))
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="running")
    write_started: Mapped[bool] = mapped_column(Boolean, default=False)
    ticket_id: Mapped[UUID | None] = mapped_column(ForeignKey("tickets.id"))
    response: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
