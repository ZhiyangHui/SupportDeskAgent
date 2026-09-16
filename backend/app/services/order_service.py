"""模拟订单服务，统一企业有效性、数据初始化与事务边界。"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversation_repository import ConversationNotFoundError
from app.db.models import Company
from app.db.order_repository import OrderRepository
from app.schema.order import OrderCreate, OrderPage, OrderResponse, OrderSearch


class OrderService:
    def __init__(
        self, session: AsyncSession, customer_id: UUID, company_id: UUID
    ) -> None:
        self.session, self.company_id = session, company_id
        self.repository = OrderRepository(session, customer_id, company_id)

    async def initialize(self) -> None:
        """首次选企业、读取订单或 Agent 查询时补齐样例；失败全部回滚。"""
        try:
            company = await self.session.get(Company, self.company_id)
            if company is None or not company.active:
                raise ConversationNotFoundError("企业不存在或已停用")
            await self.repository.seed()
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def list(
        self, query: OrderSearch, offset: int = 0, limit: int = 20
    ) -> OrderPage:
        await self.initialize()
        rows, total = await self.repository.search(query, offset, limit)
        return OrderPage(
            items=[OrderResponse.model_validate(row) for row in rows], total=total
        )

    async def create(self, data: OrderCreate) -> OrderResponse:
        await self.initialize()
        try:
            row = await self.repository.create(data)
            response = OrderResponse.model_validate(row)
            await self.session.commit()
            return response
        except Exception:
            await self.session.rollback()
            raise
