"""保存图谱草稿、人工审核快照和可重试的同步状态，不改动现有知识资料。"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20261005_20"
down_revision = "20260930_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("knowledge_graph_documents",
        sa.Column("document_id", UUID(), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("facts", JSONB(), nullable=False),
        sa.Column("approved_facts", JSONB(), nullable=False),
        sa.Column("approved_digest", sa.String(64), nullable=False),
        sa.Column("approved_revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", UUID(), sa.ForeignKey("staff_accounts.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("sync_status", sa.String(20), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("knowledge_graph_documents")
