"""创建 Agent 运行记录表。

Revision ID: 20260911_04
Revises: 20260911_03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260911_04"
down_revision: str | None = "20260911_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """保存运行结果和排错索引，不保存客户原始消息正文。"""

    # create_type=False 防止建表事件再次创建已经显式创建的 PostgreSQL 枚举。
    run_status = postgresql.ENUM(
        "running",
        "succeeded",
        "failed",
        name="agent_run_status",
        create_type=False,
    )
    run_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", run_status, nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("intent", sa.String(length=50), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=True),
        sa.Column("requires_human", sa.Boolean(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=True),
        sa.Column("ticket_code", sa.String(length=32), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(length=200), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_status_started", "agent_runs", ["status", "started_at"])
    op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])
    op.create_index("ix_agent_runs_request_id", "agent_runs", ["request_id"])


def downgrade() -> None:
    """先删除依赖枚举的表，再移除枚举类型。"""

    op.drop_index("ix_agent_runs_request_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_conversation_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_status_started", table_name="agent_runs")
    op.drop_table("agent_runs")
    postgresql.ENUM(name="agent_run_status").drop(op.get_bind(), checkfirst=True)
