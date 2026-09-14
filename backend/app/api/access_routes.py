"""双端账号 HTTP 边界；企业注册只创建新企业，禁止自行加入他人企业。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import (
    check_origin,
    cookie_name,
    customer_identity,
    require_staff,
    set_login_cookie,
)
from app.db.auth_repository import AuthRepository
from app.db.session import get_db_session
from app.schema.access import (
    CompanyRegisterRequest,
    LoginRequest,
    Principal,
    RegisterRequest,
    StaffLoginRequest,
)
from app.services.auth_service import AccountConflictError, AuthService, token_digest

router = APIRouter(prefix="/api/v1/access", tags=["双端账号"])
DB = Annotated[AsyncSession, Depends(get_db_session)]


async def throttle(request: Request, session: DB) -> None:
    check_origin(request)
    # 不信任客户端伪造的代理头；部署反向代理时需单独配置可信代理。
    key = token_digest("auth:" + (request.client.host if request.client else "unknown"))
    if not await AuthRepository(session).consume_attempt(key):
        raise HTTPException(
            429, "认证请求过于频繁，请十分钟后再试", headers={"Retry-After": "600"}
        )


async def register_account(
    body: RegisterRequest, session: AsyncSession
) -> dict[str, bool]:
    try:
        await AuthService(session).register(body)
    except AccountConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ready": True}


@router.post("/customer/register", status_code=201, dependencies=[Depends(throttle)])
async def register_customer(body: RegisterRequest, session: DB) -> dict[str, bool]:
    return await register_account(body, session)


@router.post(
    "/staff/register-company", status_code=201, dependencies=[Depends(throttle)]
)
async def register_company(
    body: CompanyRegisterRequest, session: DB
) -> dict[str, bool]:
    return await register_account(body, session)


async def login_account(
    body: LoginRequest, request: Request, response: Response, session: AsyncSession
) -> Principal:
    result = await AuthService(session).login(
        body.username,
        body.password,
        body.company_code if isinstance(body, StaffLoginRequest) else None,
    )
    if result is None:
        raise HTTPException(401, "账号、密码或企业编号不正确")
    token, principal = result
    # 轮换当前浏览器旧会话，切换账号不会留下有效的旧令牌。
    await AuthRepository(session).revoke(
        token_digest(request.cookies.get(cookie_name(principal.audience), "")),
        principal.audience,
    )
    await session.commit()
    set_login_cookie(response, principal.audience, token)
    return principal


@router.post(
    "/customer/login", response_model=Principal, dependencies=[Depends(throttle)]
)
async def login_customer(
    body: LoginRequest, request: Request, response: Response, session: DB
) -> Principal:
    return await login_account(body, request, response, session)


@router.post("/staff/login", response_model=Principal, dependencies=[Depends(throttle)])
async def login_staff(
    body: StaffLoginRequest, request: Request, response: Response, session: DB
) -> Principal:
    return await login_account(body, request, response, session)


@router.get("/customer", response_model=Principal)
async def customer_me(
    principal: Annotated[Principal, Depends(customer_identity)],
) -> Principal:
    return principal


@router.get("/staff", response_model=Principal)
async def staff_me(
    principal: Annotated[Principal, Depends(require_staff)],
) -> Principal:
    return principal


async def logout(
    audience: str, request: Request, response: Response, session: AsyncSession
) -> dict[str, bool]:
    check_origin(request)
    await AuthRepository(session).revoke(
        token_digest(request.cookies.get(cookie_name(audience), "")), audience
    )
    await session.commit()
    response.delete_cookie(cookie_name(audience))
    return {"ready": True}


@router.post("/customer/logout")
async def logout_customer(
    request: Request, response: Response, session: DB
) -> dict[str, bool]:
    return await logout("customer", request, response, session)


@router.post("/staff/logout")
async def logout_staff(
    request: Request, response: Response, session: DB
) -> dict[str, bool]:
    return await logout("staff", request, response, session)
