"""删除已清空的旧图谱审核表；不修改知识文档或任何业务表。"""
from sqlalchemy import text

from alembic import op

revision = "20261005_21"
down_revision = "20261005_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 升级不能静默丢弃旧审核数据；需先运行备份清理脚本。新安装的空表直接删除。
    connection = op.get_bind()
    connection.execute(text("LOCK TABLE knowledge_graph_documents IN ACCESS EXCLUSIVE MODE"))
    if connection.scalar(text("SELECT count(*) FROM knowledge_graph_documents")):
        raise RuntimeError("请先停止后端，运行 PYTHONPATH=. ../.venv/bin/python scripts/retire_document_graph.py --apply 备份旧图谱")
    op.drop_table("knowledge_graph_documents")


def downgrade() -> None:
    # 数据已退役，不能靠空表伪装恢复；恢复须使用退役备份及对应旧版本代码。
    raise RuntimeError("该退役迁移不支持自动降级，请使用旧图谱备份恢复")
