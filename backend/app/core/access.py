"""双端身份依赖：Cookie 和 audience 同时隔离，最终权限以数据库主体为准。"""

from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db_session
from app.schema.access import Principal
from app.services.auth_service import AuthService

CUSTOMER_COOKIE = "supportdesk_customer_v2"
STAFF_COOKIE = "supportdesk_staff_v2"


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    # 同源接口文档也允许认证；跨源网页只能来自显式配置的前端地址。
    allowed = [*get_settings().cors_origins, str(request.base_url).rstrip("/")]
    if origin and origin not in allowed:
        raise HTTPException(403, "不允许的请求来源")


def cookie_name(audience: str) -> str:
    return CUSTOMER_COOKIE if audience == "customer" else STAFF_COOKIE


def set_login_cookie(response: Response, audience: str, token: str) -> None:
    response.set_cookie(
        cookie_name(audience),
        token,
        httponly=True,
        samesite="strict",
        secure=get_settings().cookie_secure,
        max_age=8 * 60 * 60,
    )


async def resolve_identity(
    request: Request, session: AsyncSession, audience: Literal["customer", "staff"]
) -> Principal:
    check_origin(request)
    identity = await AuthService(session).resolve(
        request.cookies.get(cookie_name(audience), ""), audience
    )
    if identity is None:
        raise HTTPException(401, "登录已失效，请使用对应入口重新登录")
    return identity


async def customer_identity(
    request: Request, session: Annotated[AsyncSession, Depends(get_db_session)]
) -> Principal:
    return await resolve_identity(request, session, "customer")


async def require_staff(
    request: Request, session: Annotated[AsyncSession, Depends(get_db_session)]
) -> Principal:
    identity = await resolve_identity(request, session, "staff")
    if identity.company_id is None:
        raise HTTPException(401, "员工缺少企业归属")
    return identity
