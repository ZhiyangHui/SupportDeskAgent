"""工单经验沿用审核发布的知识库索引，新增受控来源和审核记录。"""
import sqlalchemy as sa

from alembic import op

revision = "20260929_17"
down_revision = "20260928_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_documents", sa.Column("source_kind", sa.String(30), nullable=False, server_default="document"))
    op.add_column("knowledge_documents", sa.Column("source_ticket_id", sa.Uuid(), sa.ForeignKey("tickets.id"), nullable=True))
    op.create_unique_constraint("uq_knowledge_source_ticket", "knowledge_documents", ["source_ticket_id"])
    op.add_column("knowledge_documents", sa.Column("reviewed_by", sa.Uuid(), sa.ForeignKey("staff_accounts.id"), nullable=True))
    op.add_column("knowledge_documents", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_constraint("uq_knowledge_source_ticket", "knowledge_documents", type_="unique")
    for name in ("reviewed_at", "reviewed_by", "source_ticket_id", "source_kind"):
        op.drop_column("knowledge_documents", name)
