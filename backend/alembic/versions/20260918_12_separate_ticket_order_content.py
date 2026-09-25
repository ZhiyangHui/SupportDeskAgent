"""拆分可确认的旧订单描述，原文保留在内部审计记录中。"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "20260918_12"
down_revision = "20260918_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # 只处理仍未填写独立诉求、且关联归属一致的记录；不解析自由格式的客户文字。
    rows = connection.execute(sa.text("""
        SELECT t.id, t.description, o.code, o.product_name
        FROM tickets t JOIN demo_orders o
          ON t.order_id = o.id AND t.customer_id = o.customer_id
          AND t.company_id = o.company_id
        WHERE t.desired_resolution = ''
          AND t.description LIKE '模拟订单：%'
    """)).mappings().all()
    for row in rows:
        prefix = f"模拟订单：{row['code']}\n商品：{row['product_name']}\n客户诉求："
        original = row["description"]
        if not original.startswith(prefix):
            continue
        issue = original[len(prefix):].strip()
        if not issue:
            continue
        # 固化迁移规则，不能导入将来可能变化的业务函数。复杂句保留在描述，不猜测意图。
        actions = {"退款", "退货", "换货", "维修", "退货退款"}
        only_resolution = issue in actions or any(
            issue == start + action
            for start in ("希望", "申请", "我要") for action in actions
        )
        connection.execute(sa.text("""
            INSERT INTO ticket_activities
                (id, ticket_id, activity_type, operator_name, content, from_value)
            VALUES (:id, :ticket_id, 'note_added', '系统（字段整理）', :content, 'legacy_order_split')
        """), {"id": uuid4(), "ticket_id": row["id"], "content": "字段整理前的问题描述（原文留档）：\n" + original})
        # 版本递增使迁移前尚未确认的修改预览失效，客户须核对整理后的最新内容。
        connection.execute(sa.text("""
            UPDATE tickets SET description = :description,
                desired_resolution = :resolution, version = version + 1,
                updated_at = CURRENT_TIMESTAMP WHERE id = :id
        """), {"id": row["id"], "description": "" if only_resolution else issue,
               "resolution": issue if only_resolution else ""})


def downgrade() -> None:
    # 数据整理不自动反向覆盖：迁移后客户可能已修改字段，原文仍可从审计记录追溯。
    pass
