"""模拟订单实体：每张订单同时归属客户与企业，金额仅用于演示。"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DemoOrder(Base):
    """seed_key 只用于默认三单；自建订单使用 NULL，不限制客户创建数量。"""

    __tablename__ = "demo_orders"
    __table_args__ = (
        UniqueConstraint(
            "customer_id", "company_id", "seed_key", name="uq_demo_order_seed"
        ),
        UniqueConstraint("id", "company_id", "customer_id", name="uq_demo_order_scope"),
        CheckConstraint("amount > 0", name="ck_demo_order_amount"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_accounts.id"), index=True
    )
    code: Mapped[str] = mapped_column(String(40), unique=True)
    product_name: Mapped[str] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(20))
    seed_key: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
