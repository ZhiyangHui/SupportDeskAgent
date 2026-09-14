from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import require_staff
from app.db.agent_run_repository import AgentRunNotFoundError
from app.db.models import AgentRunStatus
from app.db.session import get_db_session
from app.schema.access import Principal
from app.schema.agent_run import (
    AgentRunListResponse,
    AgentRunResponse,
    AgentRunStatisticsResponse,
)
from app.services.agent_run_service import AgentRunService

router = APIRouter(prefix="/api/v1/agent-runs", tags=["Agent 运行记录"])


@router.get("", response_model=AgentRunListResponse)
async def list_agent_runs(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    staff: Annotated[Principal, Depends(require_staff)],
    run_status: Annotated[AgentRunStatus | None, Query(alias="status")] = None,
    tool_called: bool | None = None,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AgentRunListResponse:
    """按运行状态、Tool 调用和请求 ID 等条件查询运行记录。"""

    page = await AgentRunService(session, company_id=staff.company_id).list_runs(
        status=run_status,
        tool_called=tool_called,
        keyword=keyword,
        offset=offset,
        limit=limit,
    )
    return AgentRunListResponse(
        items=[AgentRunResponse.model_validate(run) for run in page.items],
        total=page.total,
        offset=offset,
        limit=limit,
    )


@router.get("/statistics", response_model=AgentRunStatisticsResponse)
async def get_agent_run_statistics(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    staff: Annotated[Principal, Depends(require_staff)],
) -> AgentRunStatisticsResponse:
    """返回运行总数、成功率计算基础、Tool 次数和平均耗时。"""

    result = await AgentRunService(session, company_id=staff.company_id).statistics()
    return AgentRunStatisticsResponse(
        total=result.total,
        running=result.running,
        succeeded=result.succeeded,
        failed=result.failed,
        tool_calls=result.tool_calls,
        average_duration_ms=result.average_duration_ms,
    )


@router.get("/{run_id}", response_model=AgentRunResponse)
async def get_agent_run(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    staff: Annotated[Principal, Depends(require_staff)],
) -> AgentRunResponse:
    """按 ID 获取单次运行详情，便于结合 request_id 查询结构化日志。"""

    try:
        run = await AgentRunService(session, company_id=staff.company_id).get(run_id)
    except AgentRunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent 运行记录不存在",
        ) from exc
    return AgentRunResponse.model_validate(run)
