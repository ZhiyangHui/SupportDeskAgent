"""运行中心保留逐步执行结果，避免只显示最后一个工具。"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20260930_19"
down_revision = "20260930_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs", sa.Column("steps", JSONB(), nullable=False, server_default="[]")
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "steps")
