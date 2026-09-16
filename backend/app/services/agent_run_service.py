from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.agent_run_repository import (
    AgentRunPage,
    AgentRunRepository,
    AgentRunStatistics,
)
from app.db.models import AgentRun, AgentRunStatus, ChatOperation, Ticket
from app.services.agent_errors import classify_agent_error


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
        tool_name: str | None = None,
    ) -> AgentRun:
        """只记录真实完成的工具；查询没有创建工单，不能据此填充 ticket_id。"""

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
            run.tool_name = tool_name or ("create_support_ticket" if ticket_id else None)
            run.completed_at = datetime.now(UTC)
            await self.session.commit()
            return run
        except Exception:
            await self.session.rollback()
            raise

    async def fail(self, run_id: UUID, *, duration_ms: int, error: Exception, operation_id: UUID | None = None) -> AgentRun:
        """失败记录只保存异常类型和安全提示，详细堆栈通过 request_id 在日志中查询。"""

        await self.session.rollback()
        run = await self.repository.get(run_id, for_update=True)
        run.status = AgentRunStatus.FAILED
        run.duration_ms = duration_ms
        run.error_type = type(error).__name__
        run.error_message = classify_agent_error(error).detail.message
        # 工作流失败不代表工具未执行；企业运行中心也必须看到已提交的工单回执。
        operation = await self.session.get(ChatOperation, operation_id) if operation_id else None
        if operation and operation.ticket_id:
            ticket = await self.session.get(Ticket, operation.ticket_id)
            if ticket:
                run.ticket_id = ticket.id
                run.ticket_code = ticket.code
                run.tool_name = "create_support_ticket"
                run.error_message = f"工单 {ticket.code} 已创建，但后续回复或运行记录处理失败"
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
