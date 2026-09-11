"""为会话消息增加 Tool Call 展示元数据。

Revision ID: 20260911_03
Revises: 20260911_02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260911_03"
down_revision: str | None = "20260911_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """消息保留真实工具名称和安全结果摘要，使页面刷新后仍可追溯。"""

    op.add_column("messages", sa.Column("tool_name", sa.String(length=100), nullable=True))
    op.add_column("messages", sa.Column("tool_payload", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    """回滚时先删除 JSON 结果，再删除工具名称。"""

    op.drop_column("messages", "tool_payload")
    op.drop_column("messages", "tool_name")
