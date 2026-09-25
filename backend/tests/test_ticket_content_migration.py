"""用回滚事务验证历史字段整理、原文留档与两端的只读订单协议。"""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.db.models import Company, CustomerAccount, DemoOrder, Ticket, TicketActivity
from app.db.ticket_repository import TicketRepository
from app.schema.customer import CustomerTicketResponse
from app.schema.ticket import TicketResponse


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("SUPPORT_TEST_DATABASE") != "1", reason="需要本地数据库")
async def test_legacy_split_is_exact_and_keeps_original(monkeypatch):
    settings = get_settings()
    assert "localhost" in settings.database_url or "127.0.0.1" in settings.database_url
    path = Path(__file__).parents[1] / "alembic/versions/20260918_12_separate_ticket_order_content.py"
    spec = importlib.util.spec_from_file_location("content_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    suffix = uuid4().hex
                    company = Company(code=suffix, name="字段整理测试")
                    customer = CustomerAccount(username=suffix, display_name="客户", password_hash="unused")
                    session.add_all([company, customer])
                    await session.flush()
                    order = DemoOrder(company_id=company.id, customer_id=customer.id,
                                      code="MO-" + suffix, product_name="年度维护服务", amount=299, status="paid")
                    session.add(order)
                    await session.flush()
                    prefix = f"模拟订单：{order.code}\n商品：{order.product_name}\n客户诉求："
                    originals = [prefix + "维修", prefix + "设备无法启动，希望退款", "模拟订单：其他编号\n商品：年度维护服务\n客户诉求：维修", prefix + "退款"]
                    tickets = [Ticket(code="TK-" + uuid4().hex[:20], company_id=company.id,
                                      customer_id=customer.id, order_id=order.id, title="测试工单",
                                      description=value, desired_resolution="已自行填写" if index == 3 else "")
                               for index, value in enumerate(originals)]
                    session.add_all(tickets)
                    await session.flush()
                    ids = [ticket.id for ticket in tickets]

                    def migrate(sync_connection):
                        monkeypatch.setattr(migration.op, "get_bind", lambda: sync_connection)
                        migration.upgrade()
                        migration.upgrade()  # 重复执行也不能重复整理或留下重复审计。

                    await connection.run_sync(migrate)
                    for ticket in tickets:
                        await session.refresh(ticket)
                    assert tickets[0].description == "" and tickets[0].desired_resolution == "维修"
                    assert tickets[1].description == "设备无法启动，希望退款"
                    assert tickets[1].desired_resolution == ""
                    assert tickets[2].description == originals[2]
                    assert tickets[3].description == originals[3]
                    assert [ticket.version for ticket in tickets] == [2, 2, 1, 1]
                    logs = (await session.scalars(select(TicketActivity).where(TicketActivity.ticket_id.in_(ids)))).all()
                    assert len(logs) == 2
                    assert all(any(original in log.content for log in logs) for original in originals[:2])
                    detail = await TicketRepository(session, company.id).get_ticket(ids[0], with_activities=True)
                    customer_view = CustomerTicketResponse.model_validate(detail)
                    staff_view = TicketResponse.model_validate(detail)
                    assert customer_view.order == staff_view.order
                    assert customer_view.order and customer_view.order.code == order.code
                    assert customer_view.description == staff_view.description == ""
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
