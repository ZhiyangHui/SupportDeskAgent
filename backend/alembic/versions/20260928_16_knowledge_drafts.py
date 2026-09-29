"""知识分块草稿与线上索引分离；保留已有向量，不自动调用供应商重建。"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20260928_16"
down_revision = "20260925_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("draft_chunks", "draft_warnings"):
        op.add_column("knowledge_documents", sa.Column(name, JSONB(), nullable=False, server_default="[]"))
    for name in ("draft_revision", "published_revision"):
        op.add_column("knowledge_documents", sa.Column(name, sa.Integer(), nullable=False, server_default="0"))
    op.add_column("knowledge_documents", sa.Column("chunking_version", sa.String(50), nullable=False, server_default=""))
    op.add_column("knowledge_chunks", sa.Column("heading_path", sa.Text(), nullable=False, server_default=""))
    op.add_column("knowledge_chunks", sa.Column("version", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    for name in ("version", "heading_path"):
        op.drop_column("knowledge_chunks", name)
    for name in ("chunking_version", "published_revision", "draft_revision", "draft_warnings", "draft_chunks"):
        op.drop_column("knowledge_documents", name)
