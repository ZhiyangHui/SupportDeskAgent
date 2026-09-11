from dataclasses import dataclass
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.factory import get_support_graph
from app.agent.schemas import SupportIntent, TicketPriority
from app.db.conversation_repository import ConversationRepository
from app.db.models import Message, MessageRole


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

    async def chat(self, content: str, conversation_id: UUID | None) -> ChatResult:
        # 第一笔短事务确保用户输入先落库；模型失败时仍能保留原始问题。
        try:
            if conversation_id is None:
                conversation = await self.repository.create_conversation()
            else:
                conversation = await self.repository.get_conversation(conversation_id)

            customer_message = await self.repository.add_message(
                conversation.id, MessageRole.CUSTOMER, content
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        history = await self.repository.list_messages(conversation.id)
        graph_messages = [_to_langchain_message(message) for message in history]
        result = await get_support_graph().ainvoke({"messages": graph_messages})

        # 外部模型成功后再开启第二笔短事务，只保存最终对客户可见的回复。
        try:
            agent_message = await self.repository.add_message(
                conversation.id,
                MessageRole.AGENT,
                result["final_reply"],
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return ChatResult(
            conversation_id=conversation.id,
            customer_message_id=customer_message.id,
            agent_message_id=agent_message.id,
            reply=result["final_reply"],
            intent=result["intent"],
            priority=result["priority"],
            requires_human=result["requires_human"],
            reason=result["decision_reason"],
        )

    async def list_messages(self, conversation_id: UUID) -> list[Message]:
        return await self.repository.list_messages(conversation_id)