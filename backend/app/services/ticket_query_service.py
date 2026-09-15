"""把服务端已鉴权会话转换为查询范围，模型不能指定客户或企业。"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversation_repository import (
    ConversationNotFoundError,
    ConversationRepository,
)
from app.db.ticket_query_repository import TicketQueryRepository
from app.schema.ticket_query import TicketQueryInput, TicketQueryResult


class TicketQueryService:
    """查询可以覆盖同一客户在当前企业的其他会话，但绝不跨越归属边界。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self, conversation_id: UUID, query: TicketQueryInput
    ) -> TicketQueryResult:
        conversation = await ConversationRepository(self.session).get_conversation(
            conversation_id
        )
        # 旧数据可能未绑定归属，必须拒绝，不能把 None 当成不限制范围。
        if conversation.company_id is None or conversation.customer_id is None:
            raise ConversationNotFoundError("会话尚未绑定客户和企业")
        return await TicketQueryRepository(self.session).search(
            query,
            company_id=conversation.company_id,
            customer_id=conversation.customer_id,
        )
