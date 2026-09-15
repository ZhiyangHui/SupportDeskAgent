"""保存幂等请求和事务内建单回执，不修改既有工单数据。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260914_08"
down_revision = "20260912_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_operations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "customer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customer_accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("companies.id"),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("write_started", sa.Boolean(), nullable=False),
        sa.Column("ticket_id", UUID(as_uuid=True), sa.ForeignKey("tickets.id")),
        sa.Column("response", JSONB()),
        sa.Column("error", JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("chat_operations")
