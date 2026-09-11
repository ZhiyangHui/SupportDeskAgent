import json
from dataclasses import dataclass
from uuid import UUID

import structlog
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.schemas import TicketCategory, TicketPriority
from app.agent.state import SupportAgentState
from app.db.models import TicketPriorityValue, TicketSource
from app.services.ticket_service import TicketService

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SupportToolContext:
    """向 Tool 注入本次请求的可信上下文，这些字段不会暴露给模型自行填写。"""

    session: AsyncSession
    conversation_id: UUID


@tool("create_support_ticket")
async def create_support_ticket(
    title: str,
    description: str,
    category: TicketCategory,
    priority: TicketPriority,
    runtime: ToolRuntime[SupportToolContext, SupportAgentState],
) -> Command:
    """当客户明确要求建单且问题信息完整时，创建一张关联当前会话的客服工单。"""

    # Session 和会话 ID 来自服务端 Runtime Context，而不是模型参数，防止模型伪造关联关系。
    ticket = await TicketService(runtime.context.session).create_ticket(
        title=title,
        description=description,
        category=category.value,
        priority=TicketPriorityValue(priority.value),
        source=TicketSource.AGENT,
        operator_name="SupportDesk Agent",
        conversation_id=runtime.context.conversation_id,
        customer_name=None,
        customer_email=None,
    )
    tool_result = {
        "success": True,
        "ticket_id": str(ticket.id),
        "ticket_code": ticket.code,
        "status": ticket.status.value,
        "priority": ticket.priority.value,
    }
    logger.info(
        "support_ticket_tool_completed",
        tool_name="create_support_ticket",
        tool_call_id=runtime.tool_call_id,
        ticket_id=str(ticket.id),
        ticket_code=ticket.code,
        conversation_id=str(runtime.context.conversation_id),
    )
    # Command 同时回写结构化状态和 ToolMessage，LangSmith 中能够完整看到调用参数与执行结果。
    return Command(
        update={
            "created_ticket_id": ticket.id,
            "created_ticket_code": ticket.code,
            "messages": [
                ToolMessage(
                    content=json.dumps(tool_result, ensure_ascii=False),
                    tool_call_id=runtime.tool_call_id or "missing-tool-call-id",
                )
            ],
        }
    )
