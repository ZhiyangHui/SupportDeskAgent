from dataclasses import dataclass
from time import perf_counter
from uuid import UUID

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.factory import get_support_graph
from app.agent.schemas import SupportIntent, TicketPriority
from app.agent.tools import SupportToolContext
from app.core.config import get_settings
from app.core.logging import get_current_request_id
from app.db.conversation_repository import (
    ConversationNotFoundError,
    ConversationRepository,
)
from app.db.models import Company, Message, MessageRole
from app.services.agent_run_service import AgentRunService

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ChatResult:
    """Service 的稳定返回值，避免 Route 直接依赖 LangGraph 内部字典。"""

    conversation_id: UUID
    customer_message_id: UUID
    agent_message_id: UUID
    reply: str
    intent: SupportIntent
    priority: TicketPriority
    requires_human: bool
    reason: str
    created_ticket_id: UUID | None
    created_ticket_code: str | None
    agent_run_id: UUID
    queried_tickets: bool = False


def _to_langchain_message(message: Message) -> BaseMessage:
    """将数据库消息转换为 LangChain 消息，角色映射只维护在这一处。"""

    if message.role == MessageRole.CUSTOMER:
        return HumanMessage(content=message.content)
    return AIMessage(content=message.content)


class ConversationService:
    """编排会话事务、历史上下文和 Agent 调用。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ConversationRepository(session)

    async def chat(self, content: str, conversation_id: UUID | None, *, customer_id: UUID, company_id: UUID, operation_id: UUID | None = None) -> ChatResult:
        # 第一笔短事务确保用户输入先落库；模型失败时仍能保留原始问题。
        try:
            company = await self.session.get(Company, company_id)
            if company is None or not company.active:
                raise ConversationNotFoundError("企业不存在或已停用")
            if conversation_id is None:
                conversation = await self.repository.create_conversation()
                conversation.customer_id = customer_id
                conversation.company_id = company_id
            else:
                conversation = await self.repository.get_conversation(conversation_id)
                # 在读取历史、写消息和调用模型之前校验归属，越权与不存在统一返回 404。
                if conversation.customer_id != customer_id or conversation.company_id != company_id:
                    raise ConversationNotFoundError("会话不存在")

            customer_message = await self.repository.add_message(
                conversation.id, MessageRole.CUSTOMER, content
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        run_service = AgentRunService(self.session)
        started_at = perf_counter()
        run = await run_service.start(
            request_id=get_current_request_id(),
            conversation_id=conversation.id,
            model_name=get_settings().model_name,
        )
        try:
            history = await self.repository.list_messages(conversation.id)
            graph_messages = [_to_langchain_message(message) for message in history]
            result = await get_support_graph().ainvoke(
                {"messages": graph_messages},
                # 数据库 Session 和会话 ID 通过运行时上下文注入 Tool，不进入模型可见参数。
                context=SupportToolContext(session=self.session, conversation_id=conversation.id, operation_id=operation_id),
            )
            final_reply = result["final_reply"]

            # Agent 成功后保存最终客户回复，再把运行记录更新为 succeeded。
            # 查询只有执行摘要，没有新工单编号；历史页面和运行中心均使用同一份真实工具状态。
            agent_message = await self.repository.add_message(
                conversation.id,
                MessageRole.AGENT,
                final_reply,
                tool_name=(
                    "create_support_ticket" if result.get("created_ticket_code") else result.get("executed_tool")
                ),
                tool_payload=(
                    {
                        "status": "success",
                        "ticket_code": result["created_ticket_code"],
                    }
                    if result.get("created_ticket_code")
                    else {"status": "success"} if result.get("executed_tool") else None
                ),
            )
            await self.session.commit()
            duration_ms = round((perf_counter() - started_at) * 1000)
            await run_service.succeed(
                run.id,
                duration_ms=duration_ms,
                intent=result["intent"].value,
                priority=result["priority"].value,
                requires_human=result["requires_human"],
                decision_reason=result["decision_reason"],
                ticket_id=result.get("created_ticket_id"),
                ticket_code=result.get("created_ticket_code"),
                tool_name=result.get("executed_tool"),
            )
        except Exception as exc:
            duration_ms = round((perf_counter() - started_at) * 1000)
            try:
                await run_service.fail(run.id, duration_ms=duration_ms, error=exc, operation_id=operation_id)
            except Exception:
                # 运行记录写入失败不能覆盖最初的 Agent 异常，完整信息仍由同一请求 ID 串联。
                logger.exception("agent_run_failure_record_failed", agent_run_id=str(run.id))
            raise

        return ChatResult(
            conversation_id=conversation.id,
            customer_message_id=customer_message.id,
            agent_message_id=agent_message.id,
            reply=final_reply,
            intent=result["intent"],
            priority=result["priority"],
            requires_human=result["requires_human"],
            reason=result["decision_reason"],
            created_ticket_id=result.get("created_ticket_id"),
            created_ticket_code=result.get("created_ticket_code"),
            agent_run_id=run.id,
            queried_tickets=result.get("executed_tool") == "query_support_tickets",
        )

    async def list_messages(self, conversation_id: UUID) -> list[Message]:
        return await self.repository.list_messages(conversation_id)
