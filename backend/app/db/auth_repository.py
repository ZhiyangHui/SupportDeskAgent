"""认证 SQL 与跨进程共享的频率窗口，不处理 Cookie 或 HTTP 响应。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.identity_models import (
    AuthRateLimit,
    Company,
    CustomerAccount,
    LoginSession,
    StaffAccount,
)


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_account(
        self, username: str, company_code: str | None
    ) -> CustomerAccount | StaffAccount | None:
        if company_code is None:
            return await self.session.scalar(
                select(CustomerAccount).where(CustomerAccount.username == username)
            )
        return await self.session.scalar(
            select(StaffAccount)
            .join(Company)
            .where(
                Company.code == company_code,
                StaffAccount.username == username,
                Company.active.is_(True),
            )
        )

    async def consume_attempt(self, key: str) -> bool:
        """每个来源十分钟最多 30 次；失败也保留计数，避免并发绕过。"""
        now = datetime.now(UTC)
        await self.session.execute(
            delete(AuthRateLimit).where(AuthRateLimit.expires_at < now)
        )
        await self.session.execute(
            insert(AuthRateLimit)
            .values(key=key, count=0, expires_at=now + timedelta(minutes=10))
            .on_conflict_do_nothing()
        )
        row = await self.session.scalar(
            select(AuthRateLimit).where(AuthRateLimit.key == key).with_for_update()
        )
        assert row is not None
        row.count += 1
        allowed = row.count <= 30
        await self.session.commit()
        return allowed

    async def revoke(self, token_hash: str, audience: str) -> None:
        await self.session.execute(
            delete(LoginSession).where(
                LoginSession.token_hash == token_hash, LoginSession.audience == audience
            )
        )
