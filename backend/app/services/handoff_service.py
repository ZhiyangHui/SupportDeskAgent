"""人工会话与 Agent 使用同一把跨进程会话锁，不允许边接管边自动回复。"""
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversation_lock import conversation_lock
from app.db.conversation_repository import (
    ConversationNotFoundError,
)
from app.db.models import (
    Conversation,
    ConversationStatus,
    CustomerAccount,
    Message,
    MessageRole,
)
from app.schema.access import Principal
from app.schema.handoff import (
    HandoffQueueItem,
    HandoffQueuePage,
    HandoffState,
    StaffReply,
)


class HandoffConflictError(ValueError):
    """接管状态与当前操作冲突，由路由层转换为 HTTP 409。"""


class HandoffService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def queue(self, actor: Principal, scope: str, offset: int, limit: int) -> HandoffQueuePage:
        # 身份范围由服务端决定，不能让客户端传企业或客服 ID 来扩大队列可见范围。
        conditions = [Conversation.company_id == actor.company_id]
        if scope == "pending":
            conditions.extend([Conversation.status == ConversationStatus.ACTIVE,
                               Conversation.handoff_requested_at.is_not(None)])
        else:
            conditions.extend([Conversation.status == ConversationStatus.HANDED_OFF,
                               Conversation.handoff_staff_id == actor.id])
        query = select(Conversation, CustomerAccount.display_name).join(CustomerAccount, Conversation.customer_id == CustomerAccount.id).where(*conditions)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = await self.session.execute(query.order_by(Conversation.handoff_requested_at.asc().nulls_last(), Conversation.id).offset(offset).limit(limit))
        return HandoffQueuePage(total=total, items=[HandoffQueueItem(conversation_id=row.id, customer_name=name,
            requested_at=row.handoff_requested_at, reason=row.handoff_reason or "客服主动接管", status=row.status.value) for row, name in rows])

    async def owned(self, id: UUID, actor: Principal) -> Conversation:
        row = await self.session.get(Conversation, id, populate_existing=True)
        if row is None or (actor.audience == "staff" and row.company_id != actor.company_id) or (actor.audience == "customer" and row.customer_id != actor.id):
            raise ConversationNotFoundError("会话不存在")
        return row

    async def change(self, id: UUID, actor: Principal, action: str) -> HandoffState:
        await self.owned(id, actor)
        await self.session.commit()
        async with conversation_lock(self.session, id):
            row = await self.owned(id, actor)
            if row.status == ConversationStatus.CLOSED:
                raise HandoffConflictError("已关闭会话不能接管")
            if row.handoff_staff_id not in (None, actor.id):
                raise HandoffConflictError("会话已由其他客服接管")
            if action == "takeover":
                row.status, row.handoff_staff_id = ConversationStatus.HANDED_OFF, actor.id
            elif row.status == ConversationStatus.HANDED_OFF:
                row.status, row.handoff_staff_id = ConversationStatus.ACTIVE, None
                row.memory_generation += 1
                # 恢复 AI 表示本次接管结束，不让同一请求再次出现在待办队列。
                row.handoff_requested_at, row.handoff_reason = None, ""
            row.updated_at = datetime.now(UTC)
            await self.session.commit()
            return HandoffState.model_validate(row)

    async def reply(self, id: UUID, actor: Principal, data: StaffReply) -> Message:
        await self.owned(id, actor)
        await self.session.commit()
        async with conversation_lock(self.session, id):
            row = await self.owned(id, actor)
            # 消息主键绑定员工与会话，使超时重试不重复发送，也不会读取别人的回执。
            key = uuid5(NAMESPACE_URL, f"staff-reply:{actor.id}:{id}:{data.client_request_id}")
            content = f"{actor.display_name}：{data.content}"
            previous = await self.session.get(Message, key)
            if previous:
                if previous.content != content:
                    raise HandoffConflictError("同一请求标识不能用于不同内容")
                return previous
            if row.status != ConversationStatus.HANDED_OFF or row.handoff_staff_id != actor.id:
                raise HandoffConflictError("请先接管该会话再回复")
            # 与客户消息统一用实际插入时刻，避免长事务中的 now() 导致人工消息排序提前。
            message = Message(id=key, conversation_id=id, role=MessageRole.STAFF, content=content, created_at=func.clock_timestamp())
            self.session.add(message)
            row.updated_at = datetime.now(UTC)
            await self.session.commit()
            return message
