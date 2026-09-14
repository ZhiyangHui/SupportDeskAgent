"""数据库兜底校验会话和工单的企业、客户归属。

Revision ID: 20260912_07
Revises: 20260912_06
"""

from alembic import op

revision = "20260912_07"
down_revision = "20260912_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_conversation_scope_pair",
        "conversations",
        "(company_id IS NULL) = (customer_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_ticket_scope_pair",
        "tickets",
        "(company_id IS NULL) = (customer_id IS NULL)",
    )
    op.create_unique_constraint(
        "uq_conversation_scope", "conversations", ["id", "company_id", "customer_id"]
    )
    op.create_foreign_key(
        "fk_ticket_conversation_scope",
        "tickets",
        "conversations",
        ["conversation_id", "company_id", "customer_id"],
        ["id", "company_id", "customer_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_ticket_conversation_scope", "tickets", type_="foreignkey")
    op.drop_constraint("uq_conversation_scope", "conversations", type_="unique")
    op.drop_constraint("ck_ticket_scope_pair", "tickets", type_="check")
    op.drop_constraint("ck_conversation_scope_pair", "conversations", type_="check")
