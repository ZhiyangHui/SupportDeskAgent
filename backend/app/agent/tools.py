"""集中定义客服工具与可信运行上下文；业务规则和数据库访问仍由 Service、Repository 负责。"""

import asyncio
import json
from dataclasses import dataclass
from time import monotonic
from uuid import UUID

import structlog
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.schemas import TicketCategory, TicketPriority
from app.agent.state import SupportAgentState
from app.db.chat_operation import ChatOperation
from app.db.conversation_repository import (
    ConversationNotFoundError,
    ConversationRepository,
)
from app.db.models import TicketPriorityValue, TicketSource
from app.schema.order import OrderSearch
from app.schema.ticket_query import TicketQueryInput
from app.services.order_service import OrderService
from app.services.ticket_query_service import TicketQueryService
from app.services.ticket_service import TicketService

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SupportToolContext:
    """向 Tool 注入可信会话与 Session，模型不能填写这些身份字段。"""

    session: AsyncSession
    conversation_id: UUID
    operation_id: UUID | None = None


# 普通工单工具：查询与创建共用上方的可信上下文。
@tool("query_support_tickets")
async def query_support_tickets(
    runtime: ToolRuntime[SupportToolContext, SupportAgentState],
    ticket_code: str = "",
    keyword: str = "",
) -> Command:
    """查询当前客户在当前企业的工单。ticket_code 精确匹配且优先；keyword 匹配问题；都为空查最近五条。"""

    # 工具参数只允许查询条件，实际身份从 API 已验证的会话注入。
    # 数据库查询同样受总预算约束；超时抛给会话服务回滚并记录失败，不能当成空结果。
    remaining = runtime.state["query_deadline"] - monotonic()
    if remaining <= 0:
        raise TimeoutError("工单查询超过总时间预算")
    async with asyncio.timeout(min(30, remaining)):
        result = await TicketQueryService(runtime.context.session).search(
            runtime.context.conversation_id,
            TicketQueryInput(ticket_code=ticket_code, keyword=keyword),
        )
    logger.info(
        "support_ticket_query_completed",
        tool_name="query_support_tickets",
        conversation_id=str(runtime.context.conversation_id),
        tool_call_id=runtime.tool_call_id,
        result_count=len(result.items),
    )
    return Command(
        update={
            "executed_tool": "query_support_tickets",
            "query_rounds": runtime.state.get("query_rounds", 0) + 1,
            "messages": [
                ToolMessage(
                    content=result.model_dump_json(),
                    tool_call_id=runtime.tool_call_id or "missing-tool-call-id",
                )
            ],
        }
    )


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
    if runtime.context.operation_id:
        operation = await runtime.context.session.get(
            ChatOperation, runtime.context.operation_id
        )
        if operation is None:
            raise RuntimeError("缺少请求执行记录")
        # 先持久化写入尝试：进程中断或数据库无法核验时，必须保守报告结果未知。
        operation.write_started = True
        await runtime.context.session.commit()
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
        operation_id=runtime.context.operation_id,
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


# 订单工具：先确认客户订单，再创建关联工单，不执行真实退款。
class OrderTicketInput(BaseModel):
    """基本诉求足以建单，商品、金额、编号由数据库补齐。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    order_id: UUID
    issue: str = Field(min_length=2, max_length=2000)


@tool("query_my_orders")
async def query_my_orders(
    runtime: ToolRuntime[SupportToolContext, SupportAgentState],
    order_code: str = "",
    keyword: str = "",
) -> Command:
    """查询当前客户在当前企业的模拟订单。编号精确匹配，关键词匹配商品名，都为空返回最近五条。"""
    conversation = await ConversationRepository(
        runtime.context.session
    ).get_conversation(runtime.context.conversation_id)
    if not conversation.customer_id or not conversation.company_id:
        raise ConversationNotFoundError("会话缺少归属")
    page = await OrderService(
        runtime.context.session, conversation.customer_id, conversation.company_id
    ).list(OrderSearch(order_code=order_code, keyword=keyword), limit=5)
    structlog.get_logger(__name__).info(
        "order_query_completed",
        result_count=len(page.items),
        conversation_id=str(conversation.id),
    )
    return Command(
        update={
            "available_order_ids": [str(item.id) for item in page.items],
            "order_options": [
                f"{item.product_name}（{item.code}）" for item in page.items
            ],
            "order_rounds": runtime.state.get("order_rounds", 0) + 1,
            "executed_tool": "query_my_orders",
            "messages": [
                ToolMessage(
                    content=page.model_dump_json(),
                    tool_call_id=runtime.tool_call_id or "missing",
                )
            ],
        }
    )


@tool("create_order_ticket")
async def create_order_ticket(
    order_id: UUID,
    issue: str,
    runtime: ToolRuntime[SupportToolContext, SupportAgentState],
) -> Command:
    """客户明确要求建单且订单已确认后，为本轮查询到的订单创建工单；只记录诉求，不执行退款。"""
    data = OrderTicketInput(order_id=order_id, issue=issue)
    if not runtime.state.get("should_create_ticket") or runtime.state.get(
        "created_ticket_id"
    ):
        raise ValueError("当前没有建单授权或已完成建单")
    if runtime.state.get("available_order_ids", []) != [str(data.order_id)]:
        raise ValueError("请先查询并选择当前客户的订单")
    if runtime.context.operation_id:
        operation = await runtime.context.session.get(
            ChatOperation, runtime.context.operation_id
        )
        if operation is None:
            raise RuntimeError("缺少请求记录")
        operation.write_started = True
        await runtime.context.session.commit()
    ticket = await TicketService(runtime.context.session).create_ticket(
        title=data.issue[:200],
        description=data.issue,
        category="order",
        priority=TicketPriorityValue(runtime.state["priority"].value),
        source=TicketSource.AGENT,
        operator_name="SupportDesk Agent",
        conversation_id=runtime.context.conversation_id,
        customer_name=None,
        customer_email=None,
        operation_id=runtime.context.operation_id,
        order_id=data.order_id,
    )
    structlog.get_logger(__name__).info(
        "order_ticket_created", ticket_id=str(ticket.id), order_id=str(data.order_id)
    )
    return Command(
        update={
            "created_ticket_id": ticket.id,
            "created_ticket_code": ticket.code,
            "executed_tool": "create_order_ticket",
            "messages": [
                ToolMessage(
                    content=json.dumps(
                        {"ticket_code": ticket.code, "order_id": str(data.order_id)}
                    ),
                    tool_call_id=runtime.tool_call_id or "missing",
                )
            ],
        }
    )
