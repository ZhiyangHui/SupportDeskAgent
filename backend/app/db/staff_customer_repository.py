"""企业客户关系从真实咨询推导，禁止员工枚举平台全部客户。"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, CustomerAccount
from app.schema.staff_customer import StaffConversationResponse, StaffCustomerResponse


class StaffCustomerRepository:
    def __init__(self, session: AsyncSession, company_id: UUID) -> None:
        self.session = session
        self.company_id = company_id

    async def customers(
        self, offset: int, limit: int, keyword: str
    ) -> list[StaffCustomerResponse]:
        rows = await self.session.execute(
            select(
                CustomerAccount.id,
                CustomerAccount.display_name,
                func.count(Conversation.id),
                func.max(Conversation.updated_at),
            )
            .join(Conversation, Conversation.customer_id == CustomerAccount.id)
            .where(
                Conversation.company_id == self.company_id,
                CustomerAccount.display_name.contains(keyword),
            )
            .group_by(CustomerAccount.id)
            .order_by(func.max(Conversation.updated_at).desc(), CustomerAccount.id)
            .offset(offset)
            .limit(limit)
        )
        return [
            StaffCustomerResponse(
                id=id, display_name=name, conversation_count=count, updated_at=updated
            )
            for id, name, count, updated in rows
        ]

    async def conversations(
        self, customer_id: UUID | None, offset: int, limit: int
    ) -> list[StaffConversationResponse]:
        query = (
            select(Conversation, CustomerAccount.display_name)
            .join(CustomerAccount, Conversation.customer_id == CustomerAccount.id)
            .where(Conversation.company_id == self.company_id)
        )
        if customer_id:
            query = query.where(Conversation.customer_id == customer_id)
        rows = await self.session.execute(
            query.order_by(Conversation.updated_at.desc(), Conversation.id)
            .offset(offset)
            .limit(limit)
        )
        return [
            StaffConversationResponse(
                id=row.id,
                customer_id=row.customer_id,
                customer_name=name,
                updated_at=row.updated_at,
            )
            for row, name in rows
        ]
