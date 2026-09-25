"""客户修改工单：按可信会话验权、版本核对、字段白名单、原子审计与幂等回执。"""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.chat_operation import ChatOperation
from app.db.conversation_repository import (
    ConversationNotFoundError,
    ConversationRepository,
)
from app.db.models import Ticket, TicketActivity, TicketActivityType, TicketStatus
from app.db.ticket_repository import TicketRepository
from app.schema.ticket_edit import (
    EDIT_LABELS,
    CustomerTicketSnapshot,
    TicketEditInput,
    TicketEditResult,
)


class TicketEditService:
    """模型不能提供身份或写任意字段，所有持久化变更都在单笔事务内完成。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _scope(self, conversation_id: UUID) -> tuple[UUID, UUID]:
        row = await ConversationRepository(self.session).get_conversation(
            conversation_id
        )
        if not row.customer_id or not row.company_id:
            raise ConversationNotFoundError("会话缺少归属")
        return row.customer_id, row.company_id

    async def snapshot(
        self, conversation_id: UUID, code: str
    ) -> CustomerTicketSnapshot | None:
        """展示不用写锁；真正修改时重新加锁并比较版本，不能跨轮持有数据库锁。"""
        customer, company = await self._scope(conversation_id)
        row = await self.session.scalar(
            select(Ticket)
            .where(
                Ticket.code == code,
                Ticket.customer_id == customer,
                Ticket.company_id == company,
            )
            .execution_options(populate_existing=True)
        )
        result = CustomerTicketSnapshot.model_validate(row) if row else None
        await self.session.commit()
        return result

    async def update(
        self, conversation_id: UUID, operation_id: UUID, data: TicketEditInput
    ) -> TicketEditResult:
        try:
            customer, company = await self._scope(conversation_id)
            operation = await self.session.get(ChatOperation, operation_id)
            if (
                operation is None
                or operation.customer_id != customer
                or operation.company_id != company
            ):
                raise ConversationNotFoundError("请求归属不匹配")
            operation.write_started = True
            await self.session.commit()
            # 所有调用按请求行→工单行的顺序加锁；同键并发不会重复写入。
            operation = await self.session.scalar(
                select(ChatOperation)
                .where(ChatOperation.id == operation_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert operation is not None
            if operation.ticket_id or operation.comment_activity_id:
                raise ValueError("同一请求不能混用多种写操作")
            ticket = await TicketRepository(
                self.session, company
            ).get_customer_ticket_by_code(data.ticket_code, customer)
            if ticket is None:
                await self.session.rollback()
                return TicketEditResult(
                    success=False,
                    message="未找到您在当前企业的该工单，本次未修改。请重新选择工单。",
                )
            digest = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
            if operation.update_activity_id:
                activity = await self.session.get(
                    TicketActivity, operation.update_activity_id
                )
                if (
                    activity is None
                    or activity.ticket_id != ticket.id
                    or activity.to_value != digest
                ):
                    raise ValueError("同一请求不能提交不同的修改")
                result = self._success(ticket, activity)
                await self.session.commit()
                return result
            if ticket.status == TicketStatus.CLOSED:
                await self.session.rollback()
                return TicketEditResult(
                    success=False, message=f"工单 {data.ticket_code} 已关闭，不能修改。"
                )
            if ticket.version != data.expected_version:
                await self.session.rollback()
                return TicketEditResult(
                    success=False,
                    conflict=True,
                    message="工单已被更新，本次未覆盖。请继续查看最新信息并重新确认修改。",
                )
            changes = {
                key: value
                for key, value in data.changes.patch().items()
                if getattr(ticket, key) != value
            }
            if not changes:
                await self.session.commit()
                return TicketEditResult(
                    success=True,
                    message=f"工单 {data.ticket_code} 的信息与您要求一致，无需修改。",
                    ticket_code=ticket.code,
                    ticket_id=ticket.id,
                )
            # 保存修改前后的完整字段值，不覆盖历史活动；Vue 按纯文本展示，不解释其中指令。
            audit = "\n\n".join(
                f"{EDIT_LABELS[key]}\n修改前：{getattr(ticket, key) or '未填写'}\n修改后：{value or '未填写'}"
                for key, value in changes.items()
            )
            for key, value in changes.items():
                setattr(ticket, key, value)
            ticket.version += 1
            ticket.updated_at = datetime.now(UTC)
            activity = await TicketRepository(self.session, company).add_activity(
                ticket_id=ticket.id,
                activity_type=TicketActivityType.NOTE_ADDED,
                operator_name="客户（通过智能客服修改）",
                content=audit,
                from_value="customer_update",
                to_value=digest,
            )
            operation.update_activity_id = activity.id
            result = self._success(ticket, activity)
            await self.session.commit()
            return result
        except Exception:
            await self.session.rollback()
            raise

    @staticmethod
    def _success(ticket: Ticket, activity: TicketActivity) -> TicketEditResult:
        return TicketEditResult(
            success=True,
            changed=True,
            message=f"已修改工单 {ticket.code}，修改前后的记录已保存，可在工单详情中核对。",
            ticket_code=ticket.code,
            ticket_id=ticket.id,
            activity_id=activity.id,
        )
