"""后端知识包入口：内容版本化维护，新增同类解法不改查询代码。"""
from pathlib import Path

from app.schema.knowledge_graph import DomainCatalog

CATALOG_PATH = Path(__file__).with_name("after_sales.v1.json")


def load_domain_catalog() -> DomainCatalog:
    # 严格校验先于图写入：缺引用、重复编码或条件矛盾应阻止本次发布。
    return DomainCatalog.model_validate_json(CATALOG_PATH.read_text(encoding="utf-8"))
