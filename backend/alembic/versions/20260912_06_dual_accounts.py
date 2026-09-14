"""建立双账号认证和业务归属；旧记录不自动分配。

Revision ID: 20260912_06
Revises: 20260911_05
"""

import sqlalchemy as sa
from alembic import op

revision = "20260912_06"
down_revision = "20260911_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "customer_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "staff_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False
        ),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("company_id", "username"),
    )
    op.create_index("ix_staff_accounts_company_id", "staff_accounts", ["company_id"])
    op.create_table(
        "login_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("audience", sa.String(16), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customer_accounts.id")),
        sa.Column("staff_id", sa.Uuid(), sa.ForeignKey("staff_accounts.id")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(audience = 'customer' AND customer_id IS NOT NULL AND staff_id IS NULL) OR (audience = 'staff' AND staff_id IS NOT NULL AND customer_id IS NULL)",
            name="ck_session_subject",
        ),
    )
    op.create_index("ix_login_sessions_expires_at", "login_sessions", ["expires_at"])
    op.create_table(
        "auth_rate_limits",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_auth_rate_limits_expires_at", "auth_rate_limits", ["expires_at"]
    )
    for table in ("conversations", "tickets"):
        for field, target in (
            ("company_id", "companies"),
            ("customer_id", "customer_accounts"),
        ):
            op.add_column(table, sa.Column(field, sa.Uuid(), nullable=True))
            op.create_foreign_key(f"fk_{table}_{field}", table, target, [field], ["id"])
            op.create_index(f"ix_{table}_{field}", table, [field])


def downgrade() -> None:
    # 回滚会丢失账号和归属，部署前应备份；不会删除原有会话与工单。
    for table in ("tickets", "conversations"):
        for field in ("customer_id", "company_id"):
            op.drop_index(f"ix_{table}_{field}", table_name=table)
            op.drop_constraint(f"fk_{table}_{field}", table, type_="foreignkey")
            op.drop_column(table, field)
    for table in (
        "auth_rate_limits",
        "login_sessions",
        "staff_accounts",
        "customer_accounts",
        "companies",
    ):
        op.drop_table(table)
