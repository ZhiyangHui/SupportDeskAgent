from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import require_staff
from app.db.conversation_repository import ConversationNotFoundError
from app.db.models import TicketPriorityValue, TicketSource, TicketStatus
from app.db.session import get_db_session
from app.db.ticket_repository import TicketNotFoundError
from app.schema.access import Principal
from app.schema.conversation import MessageResponse
from app.schema.ticket import (
    TicketCreateRequest,
    TicketListResponse,
    TicketNoteRequest,
    TicketResponse,
    TicketStatisticsResponse,
    TicketSummaryResponse,
    TicketUpdateRequest,
)
from app.services.conversation_service import ConversationService
from app.services.ticket_service import InvalidTicketTransitionError, TicketService

router = APIRouter(prefix="/api/v1/tickets", tags=["工单"])


@router.get("/{ticket_id}/messages", response_model=list[MessageResponse])
async def get_ticket_messages(
    ticket_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    staff: Annotated[Principal, Depends(require_staff)],
) -> list[MessageResponse]:
    """企业端从已授权工单进入关联会话；只读展示，不冒充客户向 Agent 发消息。"""
    try:
        ticket = await TicketService(session, company_id=staff.company_id).get_ticket(ticket_id)
        if ticket.conversation_id is None:
            return []
        messages = await ConversationService(session).list_messages(ticket.conversation_id)
    except (TicketNotFoundError, ConversationNotFoundError) as exc:
        raise _not_found_error(exc) from exc
    return [MessageResponse(id=row.id, role=row.role, content=row.content, created_at=row.created_at) for row in messages]


def _not_found_error(exc: Exception) -> HTTPException:
    """统一隐藏内部主键和查询细节，向客户端返回稳定的 404 信息。"""

    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工单或关联会话不存在")


@router.post("", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    request: TicketCreateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    staff: Annotated[Principal, Depends(require_staff)],
) -> TicketResponse:
    """人工创建工单，也支持传入 conversation_id 将当前会话转为工单。"""

    try:
        ticket = await TicketService(session, company_id=staff.company_id).create_ticket(
            title=request.title,
            description=request.description,
            category=request.category,
            priority=request.priority,
            # 人工关联会话仍是人工创建；只有真实 Tool 调用可以标记为 Agent 来源。
            source=TicketSource.MANUAL,
            operator_name=f"{staff.display_name[:50]} ({staff.id})",
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
    staff: Annotated[Principal, Depends(require_staff)],
    ticket_status: Annotated[TicketStatus | None, Query(alias="status")] = None,
    priority: TicketPriorityValue | None = None,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    customer_id: UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TicketListResponse:
    """按状态、优先级和关键词筛选工单，并返回数据库计算的总数。"""

    page = await TicketService(session, company_id=staff.company_id).list_tickets(
        ticket_status=ticket_status,
        priority=priority,
        keyword=keyword,
        customer_id=customer_id,
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
    staff: Annotated[Principal, Depends(require_staff)],
) -> TicketStatisticsResponse:
    """提供工作台统计卡片所需的聚合数据。"""

    return TicketStatisticsResponse(**await TicketService(session, company_id=staff.company_id).get_statistics())


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    staff: Annotated[Principal, Depends(require_staff)],
) -> TicketResponse:
    try:
        ticket = await TicketService(session, company_id=staff.company_id).get_ticket(ticket_id)
    except TicketNotFoundError as exc:
        raise _not_found_error(exc) from exc
    return TicketResponse.model_validate(ticket)


@router.patch("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    ticket_id: UUID,
    request: TicketUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    staff: Annotated[Principal, Depends(require_staff)],
) -> TicketResponse:
    """修改状态、优先级或负责人，所有变化由 Service 写入审计记录。"""

    try:
        ticket = await TicketService(session, company_id=staff.company_id).update_ticket(
            ticket_id,
            ticket_status=request.status,
            priority=request.priority,
            assignee_name=request.assignee_name,
            update_assignee="assignee_name" in request.model_fields_set,
            operator_name=f"{staff.display_name[:50]} ({staff.id})",
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
    staff: Annotated[Principal, Depends(require_staff)],
) -> TicketResponse:
    """添加不可变处理备注，并返回更新后的详情和时间线。"""

    try:
        ticket = await TicketService(session, company_id=staff.company_id).add_note(
            ticket_id,
            content=request.content,
            operator_name=f"{staff.display_name[:50]} ({staff.id})",
        )
    except TicketNotFoundError as exc:
        raise _not_found_error(exc) from exc
    return TicketResponse.model_validate(ticket)
