"""增加客户可修改字段及独立修改回执，不猜测旧描述中的售后诉求。"""
from alembic import op
import sqlalchemy as sa

revision = "20260918_11"
down_revision = "20260918_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("desired_resolution", sa.Text(), nullable=False, server_default=""))
    op.add_column("tickets", sa.Column("impact_note", sa.Text(), nullable=False, server_default=""))
    op.add_column("chat_operations", sa.Column("update_activity_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_chat_operations_update_activity", "chat_operations", "ticket_activities", ["update_activity_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_chat_operations_update_activity", "chat_operations", type_="foreignkey")
    op.drop_column("chat_operations", "update_activity_id")
    op.drop_column("tickets", "impact_note")
    op.drop_column("tickets", "desired_resolution")
