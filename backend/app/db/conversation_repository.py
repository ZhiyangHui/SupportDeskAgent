from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message, MessageRole


class ConversationNotFoundError(LookupError):
    """请求指定的会话不存在时抛出，API 层会转换为 404。"""


class ConversationRepository:
    """集中管理会话和消息 SQL，不包含 Agent 编排或 HTTP 规则。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_conversation(self) -> Conversation:
        conversation = Conversation()
        self.session.add(conversation)
        # flush 获取数据库对象 ID，但事务仍由 Service 决定是否提交。
        await self.session.flush()
        return conversation

    async def get_conversation(self, conversation_id: UUID) -> Conversation:
        conversation = await self.session.get(Conversation, conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(f"会话 {conversation_id} 不存在")
        return conversation

    async def add_message(
        self,
        conversation_id: UUID,
        role: MessageRole,
        content: str,
    ) -> Message:
        message = Message(conversation_id=conversation_id, role=role, content=content)
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_messages(self, conversation_id: UUID) -> list[Message]:
        await self.get_conversation(conversation_id)
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        return list((await self.session.scalars(statement)).all())