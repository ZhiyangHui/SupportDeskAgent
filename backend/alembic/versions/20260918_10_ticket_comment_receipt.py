"""为客户补充工单增加独立回执；既有请求保持空值，历史数据不重写。"""

from alembic import op
import sqlalchemy as sa

revision = "20260918_10"
down_revision = "20260915_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_operations", sa.Column("comment_activity_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_chat_operations_comment_activity", "chat_operations", "ticket_activities", ["comment_activity_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_chat_operations_comment_activity", "chat_operations", type_="foreignkey")
    op.drop_column("chat_operations", "comment_activity_id")
