from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.agent_run_repository import (
    AgentRunPage,
    AgentRunRepository,
    AgentRunStatistics,
)
from app.db.models import AgentRun, AgentRunStatus


class AgentRunService:
    """管理 Agent 运行记录的生命周期，并明确控制每次状态变化的事务。"""

    def __init__(self, session: AsyncSession, company_id: UUID | None = None) -> None:
        self.session = session
        self.repository = AgentRunRepository(session, company_id)

    async def start(
        self,
        *,
        request_id: str,
        conversation_id: UUID,
        model_name: str,
    ) -> AgentRun:
        """模型调用前先提交 running 记录，即使后续失败也能留下排查入口。"""

        try:
            run = AgentRun(
                request_id=request_id,
                conversation_id=conversation_id,
                model_name=model_name,
                status=AgentRunStatus.RUNNING,
            )
            await self.repository.add(run)
            await self.session.commit()
            return run
        except Exception:
            await self.session.rollback()
            raise

    async def succeed(
        self,
        run_id: UUID,
        *,
        duration_ms: int,
        intent: str,
        priority: str,
        requires_human: bool,
        decision_reason: str,
        ticket_id: UUID | None,
        ticket_code: str | None,
    ) -> AgentRun:
        """记录成功结果；Tool 名称只在真实创建工单后写入。"""

        try:
            run = await self.repository.get(run_id, for_update=True)
            run.status = AgentRunStatus.SUCCEEDED
            run.duration_ms = duration_ms
            run.intent = intent
            run.priority = priority
            run.requires_human = requires_human
            run.decision_reason = decision_reason
            run.ticket_id = ticket_id
            run.ticket_code = ticket_code
            run.tool_name = "create_support_ticket" if ticket_id else None
            run.completed_at = datetime.now(UTC)
            await self.session.commit()
            return run
        except Exception:
            await self.session.rollback()
            raise

    async def fail(self, run_id: UUID, *, duration_ms: int, error: Exception) -> AgentRun:
        """失败记录只保存异常类型和安全提示，详细堆栈通过 request_id 在日志中查询。"""

        await self.session.rollback()
        run = await self.repository.get(run_id, for_update=True)
        run.status = AgentRunStatus.FAILED
        run.duration_ms = duration_ms
        run.error_type = type(error).__name__
        run.error_message = "Agent 执行失败，请使用请求 ID 查询服务端结构化日志"
        run.completed_at = datetime.now(UTC)
        await self.session.commit()
        return run

    async def get(self, run_id: UUID) -> AgentRun:
        return await self.repository.get(run_id)

    async def list_runs(
        self,
        *,
        status: AgentRunStatus | None,
        tool_called: bool | None,
        keyword: str | None,
        offset: int,
        limit: int,
    ) -> AgentRunPage:
        return await self.repository.list_runs(
            status=status,
            tool_called=tool_called,
            keyword=keyword,
            offset=offset,
            limit=limit,
        )

    async def statistics(self) -> AgentRunStatistics:
        return await self.repository.statistics()
