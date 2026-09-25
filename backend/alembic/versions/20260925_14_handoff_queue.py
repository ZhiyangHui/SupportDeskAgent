"""持久化待接管队列，并补录有明确成功运行记录的历史人工请求。"""
import sqlalchemy as sa
from alembic import op

revision = "20260925_14"
down_revision = "20260921_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("handoff_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("conversations", sa.Column("handoff_reason", sa.Text(), nullable=False, server_default=""))
    op.create_index("ix_conversation_handoff_queue", "conversations", ["company_id", "handoff_requested_at"])
    # 只补录最近一次已成功且明确需要人工的运行；不根据聊天文本猜测。
    # 已恢复过 AI 或已有人工回复的会话不重新排队，避免旧事项再次弹出。
    op.execute("""
        UPDATE conversations c SET handoff_requested_at = r.started_at,
            handoff_reason = COALESCE(r.decision_reason, '需要人工进一步核验')
        FROM (SELECT DISTINCT ON (conversation_id) conversation_id, started_at,
                     requires_human, decision_reason, status
              FROM agent_runs ORDER BY conversation_id, started_at DESC, id DESC) r
        WHERE r.conversation_id = c.id AND r.status = 'succeeded'
          AND r.requires_human IS TRUE AND c.status = 'active'
          AND c.memory_generation = 0 AND c.handoff_staff_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id AND m.role = 'staff')
    """)


def downgrade() -> None:
    op.drop_index("ix_conversation_handoff_queue", table_name="conversations")
    op.drop_column("conversations", "handoff_reason")
    op.drop_column("conversations", "handoff_requested_at")
