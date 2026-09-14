"""为访客会话增加归属摘要，保留旧数据但不自动认领。

Revision ID: 20260911_05
Revises: 20260911_04
"""

import sqlalchemy as sa
from alembic import op

revision = "20260911_05"
down_revision = "20260911_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("owner_key", sa.String(64), nullable=True))
    op.create_index("ix_conversations_owner_key", "conversations", ["owner_key"])


def downgrade() -> None:
    op.drop_index("ix_conversations_owner_key", table_name="conversations")
    op.drop_column("conversations", "owner_key")
