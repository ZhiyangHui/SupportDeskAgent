"""增加模拟订单与工单订单归属约束，既有工单保持无关联。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20260915_09"
down_revision = "20260914_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("companies.id"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customer_accounts.id"),
            nullable=False,
        ),
        sa.Column("code", sa.String(40), unique=True, nullable=False),
        sa.Column("product_name", sa.String(100), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("seed_key", sa.String(30)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "customer_id", "company_id", "seed_key", name="uq_demo_order_seed"
        ),
        sa.UniqueConstraint(
            "id", "company_id", "customer_id", name="uq_demo_order_scope"
        ),
        sa.CheckConstraint("amount > 0", name="ck_demo_order_amount"),
    )
    op.create_index("ix_demo_orders_company_id", "demo_orders", ["company_id"])
    op.create_index("ix_demo_orders_customer_id", "demo_orders", ["customer_id"])
    op.add_column("tickets", sa.Column("order_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_ticket_order", "tickets", "demo_orders", ["order_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_ticket_order_scope",
        "tickets",
        "demo_orders",
        ["order_id", "company_id", "customer_id"],
        ["id", "company_id", "customer_id"],
    )
    op.create_index("ix_tickets_order_id", "tickets", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_tickets_order_id", table_name="tickets")
    op.drop_constraint("fk_ticket_order_scope", "tickets", type_="foreignkey")
    op.drop_constraint("fk_ticket_order", "tickets", type_="foreignkey")
    op.drop_column("tickets", "order_id")
    op.drop_table("demo_orders")
