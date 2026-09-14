"""双端认证事务：注册企业不等于加入已有企业，会话令牌仅存摘要。"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.passwords import hash_password, verify_password
from app.db.auth_repository import AuthRepository
from app.db.identity_models import Company, CustomerAccount, LoginSession, StaffAccount
from app.schema.access import CompanyRegisterRequest, Principal, RegisterRequest


class AccountConflictError(ValueError):
    """账号或企业编号冲突，注册事务整体回滚。"""


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = AuthRepository(session)

    async def register(self, body: RegisterRequest) -> None:
        password_hash = await run_in_threadpool(hash_password, body.password)
        try:
            if isinstance(body, CompanyRegisterRequest):
                company = Company(code=body.company_code, name=body.company_name)
                self.session.add(company)
                await self.session.flush()
                self.session.add(
                    StaffAccount(
                        company_id=company.id,
                        username=body.username,
                        display_name=body.display_name,
                        password_hash=password_hash,
                    )
                )
            else:
                self.session.add(
                    CustomerAccount(
                        username=body.username,
                        display_name=body.display_name,
                        password_hash=password_hash,
                    )
                )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AccountConflictError("账号或企业编号已存在") from exc

    async def login(
        self, username: str, password: str, company_code: str | None
    ) -> tuple[str, Principal] | None:
        account = await self.repository.find_account(username, company_code)
        # 不存在的账号也做同等计算，降低通过响应耗时枚举用户名的风险。
        encoded = (
            account.password_hash
            if account
            else "scrypt-v1$" + "0" * 32 + "$" + "0" * 128
        )
        valid = await run_in_threadpool(verify_password, password, encoded)
        if not account or not account.active or not valid:
            return None
        audience: Literal["customer", "staff"] = (
            "staff" if isinstance(account, StaffAccount) else "customer"
        )
        token = secrets.token_hex(32)
        # 过期会话已不具备访问权，在登录事务内清理，避免长期积累无效令牌摘要。
        await self.session.execute(
            delete(LoginSession).where(LoginSession.expires_at <= datetime.now(UTC))
        )
        self.session.add(
            LoginSession(
                token_hash=token_digest(token),
                audience=audience,
                customer_id=account.id if audience == "customer" else None,
                staff_id=account.id if audience == "staff" else None,
                expires_at=datetime.now(UTC) + timedelta(hours=8),
            )
        )
        await self.session.commit()
        principal = await self.resolve(token, audience)
        assert principal is not None
        return token, principal

    async def resolve(
        self, token: str, audience: Literal["customer", "staff"]
    ) -> Principal | None:
        if len(token) != 64:
            return None
        record = await self.session.scalar(
            select(LoginSession).where(
                LoginSession.token_hash == token_digest(token),
                LoginSession.audience == audience,
                LoginSession.expires_at > datetime.now(UTC),
            )
        )
        if not record:
            return None
        if audience == "customer":
            customer = await self.session.get(CustomerAccount, record.customer_id)
            if customer and customer.active:
                return Principal(
                    id=customer.id,
                    audience=audience,
                    display_name=customer.display_name,
                )
        else:
            staff = await self.session.get(StaffAccount, record.staff_id)
            company = (
                await self.session.get(Company, staff.company_id) if staff else None
            )
            if staff and staff.active and company and company.active:
                return Principal(
                    id=staff.id,
                    audience=audience,
                    display_name=staff.display_name,
                    company_id=company.id,
                    company_name=company.name,
                )
        return None
