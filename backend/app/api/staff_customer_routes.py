"""企业按客户查看会话，所有 URL 标识均再次验证企业归属。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import require_staff
from app.db.conversation_repository import (
    ConversationNotFoundError,
    ConversationRepository,
)
from app.db.session import get_db_session
from app.db.staff_customer_repository import StaffCustomerRepository
from app.schema.access import Principal
from app.schema.conversation import MessageResponse
from app.schema.staff_customer import StaffConversationResponse, StaffCustomerResponse

router = APIRouter(prefix="/api/v1/staff", tags=["企业客户"])
DB = Annotated[AsyncSession, Depends(get_db_session)]
Staff = Annotated[Principal, Depends(require_staff)]


@router.get("/customers", response_model=list[StaffCustomerResponse])
async def customers(
    session: DB,
    staff: Staff,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[str, Query(max_length=100)] = "",
) -> list[StaffCustomerResponse]:
    assert staff.company_id is not None
    return await StaffCustomerRepository(session, staff.company_id).customers(
        offset, limit, keyword
    )


@router.get("/conversations", response_model=list[StaffConversationResponse])
async def conversations(
    session: DB,
    staff: Staff,
    customer_id: UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[StaffConversationResponse]:
    assert staff.company_id is not None
    return await StaffCustomerRepository(session, staff.company_id).conversations(
        customer_id, offset, limit
    )


@router.get(
    "/conversations/{conversation_id}/messages", response_model=list[MessageResponse]
)
async def messages(
    conversation_id: UUID, session: DB, staff: Staff
) -> list[MessageResponse]:
    repository = ConversationRepository(session)
    try:
        conversation = await repository.get_conversation(conversation_id)
        if conversation.company_id != staff.company_id:
            raise ConversationNotFoundError("会话不存在")
        rows = await repository.list_messages(conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(404, "会话不存在") from exc
    return [
        MessageResponse(
            id=row.id, role=row.role, content=row.content, created_at=row.created_at
        )
        for row in rows
    ]
