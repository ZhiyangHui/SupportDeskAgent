from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, AgentRunStatus, Conversation


class AgentRunNotFoundError(LookupError):
    """指定运行记录不存在时抛出，由 API 层转换为稳定的 404。"""


@dataclass(frozen=True, slots=True)
class AgentRunPage:
    items: list[AgentRun]
    total: int


@dataclass(frozen=True, slots=True)
class AgentRunStatistics:
    total: int
    running: int
    succeeded: int
    failed: int
    tool_calls: int
    average_duration_ms: float


class AgentRunRepository:
    """集中维护 Agent 运行记录查询，业务层不直接拼接 SQL。"""

    def __init__(self, session: AsyncSession, company_id: UUID | None = None) -> None:
        self.session = session
        self.company_id = company_id

    def scope(self):
        """运行记录通过原始会话归属隔离，包含失败运行与统计，不按工单存在与否判断。"""
        return [AgentRun.conversation_id.in_(select(Conversation.id).where(Conversation.company_id == self.company_id))] if self.company_id else []

    async def add(self, run: AgentRun) -> AgentRun:
        self.session.add(run)
        await self.session.flush()
        return run

    async def get(self, run_id: UUID, *, for_update: bool = False) -> AgentRun:
        statement = select(AgentRun).where(AgentRun.id == run_id, *self.scope())
        if for_update:
            statement = statement.with_for_update()
        run = await self.session.scalar(statement)
        if run is None:
            raise AgentRunNotFoundError(f"Agent 运行记录 {run_id} 不存在")
        return run

    async def list_runs(
        self,
        *,
        status: AgentRunStatus | None,
        tool_called: bool | None,
        keyword: str | None,
        offset: int,
        limit: int,
    ) -> AgentRunPage:
        filters = self.scope()
        if status is not None:
            filters.append(AgentRun.status == status)
        if tool_called is True:
            filters.append(AgentRun.tool_name.is_not(None))
        elif tool_called is False:
            filters.append(AgentRun.tool_name.is_(None))
        if keyword:
            pattern = f"%{keyword.strip()}%"
            filters.append(
                or_(
                    AgentRun.request_id.ilike(pattern),
                    AgentRun.model_name.ilike(pattern),
                    AgentRun.tool_name.ilike(pattern),
                    AgentRun.ticket_code.ilike(pattern),
                )
            )

        base: Select[tuple[AgentRun]] = select(AgentRun).where(*filters)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(AgentRun).where(*filters)
            )
            or 0
        )
        items = list(
            (
                await self.session.scalars(
                    base.order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        return AgentRunPage(items=items, total=total)

    async def statistics(self) -> AgentRunStatistics:
        """在数据库聚合运行状态和平均耗时，避免前端用当前分页误算。"""

        status_rows = await self.session.execute(
            select(AgentRun.status, func.count(AgentRun.id)).where(*self.scope()).group_by(AgentRun.status)
        )
        counts = {status.value: int(count) for status, count in status_rows.all()}
        average_duration = await self.session.scalar(
            select(func.avg(AgentRun.duration_ms)).where(
                *self.scope(),
                AgentRun.status == AgentRunStatus.SUCCEEDED,
                AgentRun.duration_ms.is_not(None),
            )
        )
        tool_calls = int(
            await self.session.scalar(
                select(func.count()).select_from(AgentRun).where(AgentRun.tool_name.is_not(None), *self.scope())
            )
            or 0
        )
        return AgentRunStatistics(
            total=sum(counts.values()),
            running=counts.get(AgentRunStatus.RUNNING.value, 0),
            succeeded=counts.get(AgentRunStatus.SUCCEEDED.value, 0),
            failed=counts.get(AgentRunStatus.FAILED.value, 0),
            tool_calls=tool_calls,
            average_duration_ms=round(float(average_duration or 0), 2),
        )
