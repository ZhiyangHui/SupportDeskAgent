from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ticket_schemas import (
    TicketCreateRequest,
    TicketListResponse,
    TicketNoteRequest,
    TicketResponse,
    TicketStatisticsResponse,
    TicketSummaryResponse,
    TicketUpdateRequest,
)
from app.db.conversation_repository import ConversationNotFoundError
from app.db.models import TicketPriorityValue, TicketSource, TicketStatus
from app.db.session import get_db_session
from app.db.ticket_repository import TicketNotFoundError
from app.services.ticket_service import InvalidTicketTransitionError, TicketService

router = APIRouter(prefix="/api/v1/tickets", tags=["工单"])


def _not_found_error(exc: Exception) -> HTTPException:
    """统一隐藏内部主键和查询细节，向客户端返回稳定的 404 信息。"""

    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工单或关联会话不存在")


@router.post("", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    request: TicketCreateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TicketResponse:
    """人工创建工单，也支持传入 conversation_id 将当前会话转为工单。"""

    try:
        ticket = await TicketService(session).create_ticket(
            title=request.title,
            description=request.description,
            category=request.category,
            priority=request.priority,
            # 来源是服务端可验证的业务事实，客户端不能自行把人工工单标记成 Agent 转单。
            source=TicketSource.AGENT if request.conversation_id else TicketSource.MANUAL,
            operator_name=request.operator_name,
            conversation_id=request.conversation_id,
            customer_name=request.customer_name,
            customer_email=str(request.customer_email) if request.customer_email else None,
        )
    except ConversationNotFoundError as exc:
        raise _not_found_error(exc) from exc
    return TicketResponse.model_validate(ticket)


@router.get("", response_model=TicketListResponse)
async def list_tickets(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    ticket_status: Annotated[TicketStatus | None, Query(alias="status")] = None,
    priority: TicketPriorityValue | None = None,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TicketListResponse:
    """按状态、优先级和关键词筛选工单，并返回数据库计算的总数。"""

    page = await TicketService(session).list_tickets(
        ticket_status=ticket_status,
        priority=priority,
        keyword=keyword,
        offset=offset,
        limit=limit,
    )
    return TicketListResponse(
        items=[TicketSummaryResponse.model_validate(ticket) for ticket in page.items],
        total=page.total,
        offset=offset,
        limit=limit,
    )


@router.get("/statistics", response_model=TicketStatisticsResponse)
async def get_ticket_statistics(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TicketStatisticsResponse:
    """提供工作台统计卡片所需的聚合数据。"""

    return TicketStatisticsResponse(**await TicketService(session).get_statistics())


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TicketResponse:
    try:
        ticket = await TicketService(session).get_ticket(ticket_id)
    except TicketNotFoundError as exc:
        raise _not_found_error(exc) from exc
    return TicketResponse.model_validate(ticket)


@router.patch("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    ticket_id: UUID,
    request: TicketUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TicketResponse:
    """修改状态、优先级或负责人，所有变化由 Service 写入审计记录。"""

    try:
        ticket = await TicketService(session).update_ticket(
            ticket_id,
            ticket_status=request.status,
            priority=request.priority,
            assignee_name=request.assignee_name,
            update_assignee="assignee_name" in request.model_fields_set,
            operator_name=request.operator_name,
        )
    except TicketNotFoundError as exc:
        raise _not_found_error(exc) from exc
    except InvalidTicketTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return TicketResponse.model_validate(ticket)


@router.post("/{ticket_id}/notes", response_model=TicketResponse)
async def add_ticket_note(
    ticket_id: UUID,
    request: TicketNoteRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TicketResponse:
    """添加不可变处理备注，并返回更新后的详情和时间线。"""

    try:
        ticket = await TicketService(session).add_note(
            ticket_id,
            content=request.content,
            operator_name=request.operator_name,
        )
    except TicketNotFoundError as exc:
        raise _not_found_error(exc) from exc
    return TicketResponse.model_validate(ticket)
