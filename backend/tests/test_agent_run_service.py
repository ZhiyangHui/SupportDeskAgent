from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.models import AgentRun, AgentRunStatus
from app.services.agent_run_service import AgentRunService


def build_running_record() -> AgentRun:
    """构造运行中的记录，测试状态收尾逻辑而不连接真实数据库。"""

    return AgentRun(
        id=uuid4(),
        request_id="run-service-test-001",
        conversation_id=uuid4(),
        status=AgentRunStatus.RUNNING,
        model_name="deepseek-v4-flash",
    )


@pytest.mark.asyncio
async def test_agent_run_success_records_tool_and_ticket() -> None:
    """成功运行必须写入判断结果、Tool、工单和完成耗时。"""

    session = AsyncMock()
    service = AgentRunService(session)
    run = build_running_record()
    ticket_id = uuid4()
    service.repository.get = AsyncMock(return_value=run)

    result = await service.succeed(
        run.id,
        duration_ms=1250,
        intent="ticket",
        priority="high",
        requires_human=True,
        decision_reason="用户明确要求创建工单",
        ticket_id=ticket_id,
        ticket_code="TK-TEST-001",
    )

    assert result.status == AgentRunStatus.SUCCEEDED
    assert result.tool_name == "create_support_ticket"
    assert result.ticket_id == ticket_id
    assert result.duration_ms == 1250
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_run_failure_keeps_safe_error_summary() -> None:
    """失败记录保留异常类型，但不能把原始异常正文写进数据库。"""

    session = AsyncMock()
    service = AgentRunService(session)
    run = build_running_record()
    service.repository.get = AsyncMock(return_value=run)

    result = await service.fail(
        run.id,
        duration_ms=800,
        error=RuntimeError("可能包含上游响应正文的内部错误"),
    )

    assert result.status == AgentRunStatus.FAILED
    assert result.error_type == "RuntimeError"
    assert "上游响应正文" not in (result.error_message or "")
    session.rollback.assert_awaited_once()
    session.commit.assert_awaited_once()
