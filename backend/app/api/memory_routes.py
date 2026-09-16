"""显式客户偏好入口；聊天不会自动提取个人信息写入长期记忆。"""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.agent.persistence import get_memory_resources
from app.api.customer_routes import DB, Customer
from app.db.models import Company
from app.schema.memory import CustomerPreferences
from app.services.customer_memory_service import CustomerMemoryService

router = APIRouter(
    prefix="/api/v1/customer/companies/{company_id}/preferences", tags=["客户长期记忆"]
)


async def memory_service(
    company_id: UUID, customer: Customer, session: DB
) -> CustomerMemoryService:
    """身份来自已认证 Cookie，不能由请求体指定其他客户命名空间。"""
    company = await session.get(Company, company_id)
    if company is None or not company.active:
        raise HTTPException(404, "企业不存在或已停用")
    return CustomerMemoryService(get_memory_resources().store, company_id, customer.id)


@router.get("", response_model=CustomerPreferences)
async def read_preferences(
    company_id: UUID, customer: Customer, session: DB
) -> CustomerPreferences:
    return await (await memory_service(company_id, customer, session)).read()


@router.put("", response_model=CustomerPreferences)
async def save_preferences(
    company_id: UUID, body: CustomerPreferences, customer: Customer, session: DB
) -> CustomerPreferences:
    await (await memory_service(company_id, customer, session)).save(body)
    return body


@router.delete("", response_model=CustomerPreferences)
async def clear_preferences(
    company_id: UUID, customer: Customer, session: DB
) -> CustomerPreferences:
    await (await memory_service(company_id, customer, session)).clear()
    return CustomerPreferences()
