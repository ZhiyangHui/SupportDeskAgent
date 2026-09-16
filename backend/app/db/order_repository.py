"""所有订单查询都携带双重归属条件；默认订单通过唯一键实现并发安全初始化。"""

from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.order_models import DemoOrder
from app.schema.order import OrderCreate, OrderSearch


class OrderRepository:
    def __init__(
        self, session: AsyncSession, customer_id: UUID, company_id: UUID
    ) -> None:
        self.session, self.customer_id, self.company_id = (
            session,
            customer_id,
            company_id,
        )

    def scope(self):
        return (
            DemoOrder.customer_id == self.customer_id,
            DemoOrder.company_id == self.company_id,
        )

    async def seed(self) -> None:
        """每家企业各三条固定样例；不能用订单总数判断，否则自建订单会影响初始化。"""
        for key, name, amount, status in [
            ("machine", "家用机械设备", "1299.00", "completed"),
            ("keyboard", "无线键盘", "199.00", "shipped"),
            ("service", "年度维护服务", "299.00", "paid"),
        ]:
            order_id = uuid5(
                NAMESPACE_URL, f"demo:{self.customer_id}:{self.company_id}:{key}"
            )
            await self.session.execute(
                insert(DemoOrder)
                .values(
                    id=order_id,
                    company_id=self.company_id,
                    customer_id=self.customer_id,
                    code="MO-" + order_id.hex,
                    product_name=name,
                    amount=amount,
                    status=status,
                    seed_key=key,
                )
                .on_conflict_do_nothing(constraint="uq_demo_order_seed")
            )

    async def create(self, data: OrderCreate) -> DemoOrder:
        # 同一次手动创建复用客户端键，网络响应丢失后的重发不会产生第二张订单。
        order_id = uuid5(
            NAMESPACE_URL,
            f"manual-order:{self.customer_id}:{self.company_id}:{data.client_request_id}",
        )
        await self.session.execute(
            insert(DemoOrder)
            .values(
                id=order_id,
                company_id=self.company_id,
                customer_id=self.customer_id,
                code="MO-" + uuid4().hex,
                **data.model_dump(exclude={"client_request_id"}),
            )
            .on_conflict_do_nothing(index_elements=[DemoOrder.id])
        )
        row = await self.get(order_id)
        assert row is not None
        if (row.product_name, row.amount, row.status) != (
            data.product_name,
            data.amount,
            data.status,
        ):
            raise ValueError("同一请求标识不能用于不同订单内容")
        return row

    async def get(self, order_id: UUID) -> DemoOrder | None:
        return await self.session.scalar(
            select(DemoOrder).where(*self.scope(), DemoOrder.id == order_id)
        )

    async def search(
        self, query: OrderSearch, offset: int = 0, limit: int = 20
    ) -> tuple[list[DemoOrder], int]:
        statement = select(DemoOrder).where(*self.scope())
        if query.order_code:
            statement = statement.where(DemoOrder.code == query.order_code)
        elif query.keyword:
            statement = statement.where(
                DemoOrder.product_name.icontains(query.keyword, autoescape=True)
            )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        rows = await self.session.scalars(
            statement.order_by(DemoOrder.created_at.desc(), DemoOrder.id)
            .offset(offset)
            .limit(limit)
        )
        return list(rows), total or 0
