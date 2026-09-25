"""客户只读接管状态；接管、恢复与人工回复仅开放给本企业员工。"""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import customer_identity, require_staff
from app.db.conversation_lock import ConversationBusyError
from app.db.conversation_repository import ConversationNotFoundError
from app.db.session import get_db_session
from app.schema.access import Principal
from app.schema.conversation import MessageResponse
from app.schema.handoff import HandoffAction, HandoffQueuePage, HandoffState, StaffReply
from app.services.handoff_service import HandoffConflictError, HandoffService

router = APIRouter(prefix="/api/v1", tags=["人工接管"])
DB = Annotated[AsyncSession, Depends(get_db_session)]
Staff = Annotated[Principal, Depends(require_staff)]
Customer = Annotated[Principal, Depends(customer_identity)]


@router.get("/staff/handoffs", response_model=HandoffQueuePage)
async def queue(actor: Staff, session: DB, scope: Literal["pending", "mine"] = "pending",
                offset: Annotated[int, Query(ge=0)] = 0,
                limit: Annotated[int, Query(ge=1, le=100)] = 20) -> HandoffQueuePage:
    return await HandoffService(session).queue(actor, scope, offset, limit)


async def state(id: UUID, actor: Principal, session: AsyncSession) -> HandoffState:
    try:
        return HandoffState.model_validate(await HandoffService(session).owned(id, actor))
    except ConversationNotFoundError as exc:
        raise HTTPException(404, "会话不存在") from exc


@router.get("/customer/conversations/{id}/handoff", response_model=HandoffState)
async def customer_state(id: UUID, actor: Customer, session: DB) -> HandoffState:
    return await state(id, actor, session)


@router.get("/staff/conversations/{id}/handoff", response_model=HandoffState)
async def staff_state(id: UUID, actor: Staff, session: DB) -> HandoffState:
    return await state(id, actor, session)


@router.post("/staff/conversations/{id}/handoff", response_model=HandoffState)
async def change(id: UUID, data: HandoffAction, actor: Staff, session: DB) -> HandoffState:
    try:
        return await HandoffService(session).change(id, actor, data.action)
    except ConversationNotFoundError as exc:
        raise HTTPException(404, "会话不存在") from exc
    except ConversationBusyError as exc:
        raise HTTPException(409, "会话正在处理消息，请稍后重试接管操作") from exc
    except HandoffConflictError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/staff/conversations/{id}/reply", response_model=MessageResponse)
async def reply(id: UUID, data: StaffReply, actor: Staff, session: DB) -> MessageResponse:
    try:
        row = await HandoffService(session).reply(id, actor, data)
        return MessageResponse(id=row.id, role=row.role, content=row.content, created_at=row.created_at)
    except ConversationNotFoundError as exc:
        raise HTTPException(404, "会话不存在") from exc
    except ConversationBusyError as exc:
        raise HTTPException(409, "会话正在处理消息，请稍后重试") from exc
    except HandoffConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
