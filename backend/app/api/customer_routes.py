"""客户企业目录、个人会话与工单 API，不能访问内部备注或其他客户信息。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import customer_identity
from app.db.customer_repository import CustomerRepository
from app.db.models import Company
from app.db.session import get_db_session
from app.schema.access import CompanyResponse, Principal
from app.schema.customer import (
    ConversationSummary,
    CustomerTicketPage,
    CustomerTicketResponse,
)
from app.services.order_service import OrderService

router = APIRouter(prefix="/api/v1/customer", tags=["客户服务"])
DB = Annotated[AsyncSession, Depends(get_db_session)]
Customer = Annotated[Principal, Depends(customer_identity)]


@router.get("/companies/{company_id}", response_model=CompanyResponse)
async def company_detail(
    company_id: UUID, customer: Customer, session: DB
) -> CompanyResponse:
    row = await session.get(Company, company_id)
    if row is None or not row.active:
        raise HTTPException(404, "企业不存在或已停用")
    # 懒初始化覆盖老用户，首次进入企业就有三条样例；唯一约束避免刷新或并发重复创建。
    await OrderService(session, customer.id, company_id).initialize()
    return CompanyResponse.model_validate(row)


@router.get("/companies", response_model=list[CompanyResponse])
async def companies(
    customer: Customer,
    session: DB,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[str, Query(max_length=100)] = "",
) -> list[CompanyResponse]:
    rows = await session.scalars(
        select(Company)
        .where(Company.active.is_(True), Company.name.contains(keyword))
        .order_by(Company.name, Company.id)
        .offset(offset)
        .limit(limit)
    )
    return [CompanyResponse.model_validate(row) for row in rows]


@router.get("/conversations", response_model=list[ConversationSummary])
async def conversations(
    company_id: UUID,
    customer: Customer,
    session: DB,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[ConversationSummary]:
    rows = await CustomerRepository(session).list_conversations(
        customer.id, company_id, offset, limit
    )
    return [ConversationSummary.model_validate(row) for row in rows]


@router.get("/tickets", response_model=CustomerTicketPage)
async def list_my_tickets(
    customer: Customer,
    session: DB,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CustomerTicketPage:
    rows, total = await CustomerRepository(session).list_tickets(
        customer.id, offset, limit
    )
    return CustomerTicketPage(
        items=[
            CustomerTicketResponse.model_validate(ticket).model_copy(
                update={"company_name": name}
            )
            for ticket, name in rows
        ],
        total=total,
    )
