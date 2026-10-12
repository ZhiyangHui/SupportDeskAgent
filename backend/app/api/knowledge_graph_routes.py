"""员工只读领域知识入口；不再提供文档抽取、手工建图、审核或发布接口。"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.access import require_staff
from app.db.knowledge_graph import GraphUnavailableError, KnowledgeGraphStore
from app.knowledge.domain_catalog import load_domain_catalog
from app.schema.access import Principal
from app.schema.knowledge_graph import DomainCatalog, GraphStatus

router = APIRouter(prefix="/api/v1/staff/knowledge-graph", tags=["售后领域知识"])
Staff = Annotated[Principal, Depends(require_staff)]


async def read_catalog(request: Request) -> DomainCatalog:
    store: KnowledgeGraphStore | None = getattr(request.app.state, "knowledge_graph", None)
    if store is None:
        raise HTTPException(503, "领域图谱未启用，请配置 SUPPORT_GRAPH_ENABLED=true 并重启后端")
    try:
        return await store.read(load_domain_catalog().id)
    except GraphUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/status", response_model=GraphStatus)
async def status(request: Request, staff: Staff) -> GraphStatus:
    if getattr(request.app.state, "knowledge_graph", None) is None:
        return GraphStatus(enabled=False, ready=False, message="领域图谱未启用")
    catalog = await read_catalog(request)
    return GraphStatus(enabled=True, ready=True, message=f"领域知识版本 {catalog.version} 已就绪，共 {len(catalog.paths)} 条排查路径")


@router.get("/catalog", response_model=DomainCatalog)
async def catalog(request: Request, staff: Staff) -> DomainCatalog:
    # 这里只包含后端部署的通用知识，无企业私有文档、客户身份或订单工单记录。
    return await read_catalog(request)
