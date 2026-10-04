from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.factory import get_support_graph
from app.agent.schemas import SupportIntent, TicketPriority
from app.agent.tools import SupportToolContext
from app.core.config import get_settings
from app.core.logging import get_current_request_id
from app.db.chat_operation import ChatOperation
from app.db.conversation_lock import conversation_lock
from app.db.conversation_repository import (
    ConversationNotFoundError,
    ConversationRepository,
)
from app.db.models import Company, ConversationStatus, Message, MessageRole
from app.services.agent_memory_service import run_graph_turn
from app.services.agent_run_service import AgentRunService
from app.services.agent_trace import AgentTrace

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ChatResult:
    """Service 的稳定返回值，避免 Route 直接依赖 LangGraph 内部字典。"""

    conversation_id: UUID
    customer_message_id: UUID
    agent_message_id: UUID | None
    reply: str
    intent: SupportIntent
    priority: TicketPriority
    requires_human: bool
    reason: str
    created_ticket_id: UUID | None
    created_ticket_code: str | None
    agent_run_id: UUID | None
    delivery_mode: str = "agent"
    queried_tickets: bool = False
    executed_tool: str | None = None
    commented_ticket_code: str | None = None
    updated_ticket_code: str | None = None


class ConversationService:
    """编排会话事务、历史上下文和 Agent 调用。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ConversationRepository(session)

    async def chat(self, content: str, conversation_id: UUID | None, *, customer_id: UUID, company_id: UUID, operation_id: UUID | None = None) -> ChatResult:
        # 在获取锁及访问检查点之前验证归属，防止利用别人的 ID 读取或阻塞其线程。
        if conversation_id:
            row = await self.repository.get_conversation(conversation_id)
            if row.customer_id != customer_id or row.company_id != company_id:
                raise ConversationNotFoundError("会话不存在")
            await self.session.commit()
        async with conversation_lock(self.session, conversation_id):
            return await self._chat(content, conversation_id, customer_id=customer_id, company_id=company_id, operation_id=operation_id)

    async def _chat(self, content: str, conversation_id: UUID | None, *, customer_id: UUID, company_id: UUID, operation_id: UUID | None = None) -> ChatResult:
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
            if conversation.status == ConversationStatus.HANDED_OFF:
                # 人工模式只落客户消息，不调用模型、不创建虚假的 Agent 消息或运行记录。
                human_result = ChatResult(
                    conversation_id=conversation.id, customer_message_id=customer_message.id,
                    agent_message_id=None, reply="", intent=SupportIntent.GENERAL,
                    priority=TicketPriority.MEDIUM, requires_human=True,
                    reason="消息已提交人工客服", created_ticket_id=None, created_ticket_code=None,
                    agent_run_id=None, delivery_mode="human",
                )
                if operation_id:
                    from dataclasses import asdict

                    from app.schema.conversation import ChatResponse
                    operation = await self.session.get(ChatOperation, operation_id)
                    assert operation is not None
                    # 客户消息与回执同事务，避免响应丢失后重试造成重复消息。
                    operation.response = ChatResponse.model_validate(asdict(human_result)).model_dump(mode="json")
                    operation.status = "completed"
                await self.session.commit()
                return human_result
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
        trace = AgentTrace()
        try:
            history = await self.repository.list_messages(conversation.id)
            result = await run_graph_turn(
                get_support_graph(), history, customer_message,
                SupportToolContext(session=self.session, conversation_id=conversation.id,
                    operation_id=operation_id, customer_id=customer_id, company_id=company_id,
                    memory_generation=conversation.memory_generation),
                callbacks=[trace],
            )
            final_reply = result["final_reply"]
            if result["requires_human"]:
                # 与最终回复同事务保存排队状态；重复提出人工需求不重置等待起点。
                conversation.handoff_requested_at = conversation.handoff_requested_at or datetime.now(UTC)
                conversation.handoff_reason = result["decision_reason"]
            comment = result.get("comment_result")
            commented_code = comment.ticket_code if comment and comment.success else None
            edit = result.get("edit_result")
            updated_code = edit.ticket_code if edit and edit.success and edit.changed else None

            # Agent 成功后保存最终客户回复，再把运行记录更新为 succeeded。
            # 查询只有执行摘要，没有新工单编号；历史页面和运行中心均使用同一份真实工具状态。
            agent_message = await self.repository.add_message(
                conversation.id,
                MessageRole.AGENT,
                final_reply,
                tool_name=(
                    result.get("executed_tool") or ("create_support_ticket" if result.get("created_ticket_code") else None)
                ),
                tool_payload=(
                    {
                        "status": "success",
                        "ticket_code": result.get("created_ticket_code") or updated_code or commented_code or "",
                    }
                    if result.get("created_ticket_code") or updated_code or commented_code
                    else {
                        "status": "success",
                    } if result.get("executed_tool") else None
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
                ticket_id=result.get("created_ticket_id") or (edit.ticket_id if edit and edit.changed else None) or (comment.ticket_id if comment and comment.success else None),
                ticket_code=result.get("created_ticket_code") or updated_code or commented_code,
                tool_name=result.get("executed_tool"),
                steps=trace.steps,
            )
        except Exception as exc:
            duration_ms = round((perf_counter() - started_at) * 1000)
            try:
                await run_service.fail(run.id, duration_ms=duration_ms, error=exc, operation_id=operation_id, steps=trace.steps)
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
            executed_tool=result.get("executed_tool"),
            commented_ticket_code=commented_code,
            updated_ticket_code=updated_code,
        )

    async def list_messages(self, conversation_id: UUID) -> list[Message]:
        return await self.repository.list_messages(conversation_id)
