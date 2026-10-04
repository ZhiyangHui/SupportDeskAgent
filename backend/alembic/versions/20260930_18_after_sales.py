"""补充模拟订单签收日期，保留老数据未知状态。"""

import sqlalchemy as sa

from alembic import op

revision = "20260930_18"
down_revision = "20260929_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("demo_orders", sa.Column("received_on", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("demo_orders", "received_on")
