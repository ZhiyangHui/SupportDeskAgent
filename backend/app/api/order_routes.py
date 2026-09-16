"""客户模拟订单接口，身份来自 Cookie，不接受用户自行指定 customer_id。"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.api.customer_routes import DB, Customer
from app.db.conversation_repository import ConversationNotFoundError
from app.schema.order import OrderCreate, OrderPage, OrderResponse, OrderSearch
from app.services.order_service import OrderService

router = APIRouter(
    prefix="/api/v1/customer/companies/{company_id}/orders", tags=["模拟订单"]
)


@router.get("", response_model=OrderPage)
async def list_orders(
    company_id: UUID,
    customer: Customer,
    session: DB,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> OrderPage:
    try:
        return await OrderService(session, customer.id, company_id).list(
            OrderSearch(), offset, limit
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(404, "企业不存在或已停用") from exc


@router.post("", response_model=OrderResponse, status_code=201)
async def create_order(
    company_id: UUID, body: OrderCreate, customer: Customer, session: DB
) -> OrderResponse:
    try:
        return await OrderService(session, customer.id, company_id).create(body)
    except ConversationNotFoundError as exc:
        raise HTTPException(404, "企业不存在或已停用") from exc
    except ValueError as exc:
        raise HTTPException(409, "请求标识与原订单内容冲突，请重新提交") from exc
