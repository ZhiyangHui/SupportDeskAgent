"""最小人工接管：接管人、记忆代次和独立人工消息角色。"""
import sqlalchemy as sa
from alembic import op

revision = "20260921_13"
down_revision = "20260918_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE message_role ADD VALUE IF NOT EXISTS 'staff'")
    op.add_column("conversations", sa.Column("handoff_staff_id", sa.Uuid(), sa.ForeignKey("staff_accounts.id"), nullable=True))
    op.add_column("conversations", sa.Column("memory_generation", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("conversations", "memory_generation")
    op.drop_column("conversations", "handoff_staff_id")
    # PostgreSQL 枚举值不强行删除，保留已保存人工消息的身份信息。
