"""创建工单与工单审计记录表。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260911_02"
down_revision: str | None = "20260906_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """以可回滚迁移创建工单领域表和稳定枚举。"""

    ticket_status = postgresql.ENUM(
        "open", "in_progress", "waiting_customer", "resolved", "closed",
        name="ticket_status", create_type=False,
    )
    ticket_priority = postgresql.ENUM(
        "low", "medium", "high", "urgent", name="ticket_priority", create_type=False
    )
    ticket_source = postgresql.ENUM(
        "manual", "agent", name="ticket_source", create_type=False
    )
    activity_type = postgresql.ENUM(
        "created", "status_changed", "priority_changed", "assigned", "note_added",
        name="ticket_activity_type", create_type=False,
    )
    bind = op.get_bind()
    for enum_type in (ticket_status, ticket_priority, ticket_source, activity_type):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("status", ticket_status, nullable=False),
        sa.Column("priority", ticket_priority, nullable=False),
        sa.Column("source", ticket_source, nullable=False),
        sa.Column("customer_name", sa.String(length=100), nullable=True),
        sa.Column("customer_email", sa.String(length=320), nullable=True),
        sa.Column("assignee_name", sa.String(length=100), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_tickets_conversation_id", "tickets", ["conversation_id"])
    op.create_index(
        "ix_tickets_status_priority_updated", "tickets", ["status", "priority", "updated_at"]
    )

    op.create_table(
        "ticket_activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_type", activity_type, nullable=False),
        sa.Column("operator_name", sa.String(length=100), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("from_value", sa.String(length=100), nullable=True),
        sa.Column("to_value", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ticket_activities_ticket_created",
        "ticket_activities",
        ["ticket_id", "created_at", "id"],
    )


def downgrade() -> None:
    """先删除依赖表，再清理枚举类型，保证迁移可以完整回滚。"""

    op.drop_index("ix_ticket_activities_ticket_created", table_name="ticket_activities")
    op.drop_table("ticket_activities")
    op.drop_index("ix_tickets_status_priority_updated", table_name="tickets")
    op.drop_index("ix_tickets_conversation_id", table_name="tickets")
    op.drop_table("tickets")
    bind = op.get_bind()
    for name in ("ticket_activity_type", "ticket_source", "ticket_priority", "ticket_status"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
