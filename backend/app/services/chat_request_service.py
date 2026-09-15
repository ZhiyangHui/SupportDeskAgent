"""请求级幂等编排：先取得数据库执行权，再运行会话流程，最后保存可重放结果。"""

import hashlib
import json
from dataclasses import asdict
from uuid import NAMESPACE_URL, uuid5

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_current_request_id
from app.db.chat_operation import ChatOperation
from app.db.chat_operation_repository import ChatOperationRepository
from app.db.conversation_repository import (
    ConversationNotFoundError,
    ConversationRepository,
)
from app.db.models import Company, Ticket
from app.schema.access import Principal
from app.schema.agent_error import AgentErrorDetail, AgentRequestError
from app.schema.conversation import ChatRequest, ChatResponse
from app.services.agent_errors import classify_agent_error
from app.services.conversation_service import ConversationService

logger = structlog.get_logger(__name__)


class ChatRequestService:
    """同一键只有首次请求运行 Graph；未知结果永不自动重新执行写操作。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def chat(self, request: ChatRequest, customer: Principal) -> ChatResponse:
        # 在创建请求记录之前完成授权校验，非法企业或会话不能留下业务执行记录。
        company = await self.session.get(Company, request.company_id)
        if company is None or not company.active:
            raise ConversationNotFoundError("企业不存在或已停用")
        if request.conversation_id:
            conversation = await ConversationRepository(self.session).get_conversation(
                request.conversation_id
            )
            if (
                conversation.customer_id != customer.id
                or conversation.company_id != request.company_id
            ):
                raise ConversationNotFoundError("会话不存在")
        # 键绑定可信身份；另一个客户即使知道键，也不能读取原请求的回执。
        key = uuid5(
            NAMESPACE_URL,
            f"supportdesk:{customer.id}:{request.company_id}:{request.client_request_id}",
        )
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "message": request.message,
                    "conversation_id": str(request.conversation_id),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        claimed = await ChatOperationRepository(self.session).claim(
            key,
            customer_id=customer.id,
            company_id=request.company_id,
            fingerprint=fingerprint,
        )
        await self.session.commit()
        operation = await self.session.get(ChatOperation, key)
        assert operation is not None
        if not claimed:
            if operation.fingerprint != fingerprint:
                raise AgentRequestError(
                    AgentErrorDetail(
                        code="idempotency_conflict",
                        message="同一请求标识不能用于不同内容，请重新发起请求。",
                        request_id=get_current_request_id(),
                    ),
                    409,
                )
            if operation.response:
                return ChatResponse.model_validate(operation.response)
            if operation.error:
                saved = operation.error
                detail = AgentErrorDetail.model_validate(saved["detail"])
                detail.request_id = get_current_request_id()
                raise AgentRequestError(detail, saved["status"])
            # running 可能来自并发请求或进程中断；都不能按超时猜测失败并再次执行。
            ticket = (
                await self.session.get(Ticket, operation.ticket_id)
                if operation.ticket_id
                else None
            )
            raise AgentRequestError(
                AgentErrorDetail(
                    code="request_in_progress",
                    message=(
                        f"工单 {ticket.code} 已创建，请到我的工单查看。"
                        if ticket
                        else "原请求仍在处理或等待核对，请勿重复建单，可稍后使用原请求重试查询结果。"
                    ),
                    request_id=get_current_request_id(),
                    outcome="ticket_created" if ticket else "unknown",
                    ticket_code=ticket.code if ticket else None,
                ),
                409,
            )
        # 释放读取事务后再等待模型，避免幂等记录长期占用数据库事务。
        await self.session.commit()
        try:
            result = await ConversationService(self.session).chat(
                request.message,
                request.conversation_id,
                customer_id=customer.id,
                company_id=request.company_id,
                operation_id=key,
            )
            response = ChatResponse.model_validate(asdict(result))
            operation = await self.session.get(ChatOperation, key)
            assert operation is not None
            operation.response = response.model_dump(mode="json")
            operation.status = "completed"
            await self.session.commit()
            return response
        except Exception as exc:
            logger.exception(
                "agent_request_failed",
                operation_id=str(key),
                error_type=type(exc).__name__,
            )
            failure = classify_agent_error(exc)
            try:
                await self.session.rollback()
                # 强制重读回执，不能使用回滚前缓存的 ORM 状态判断副作用。
                operation = await self.session.get(
                    ChatOperation, key, populate_existing=True
                )
                assert operation is not None
                ticket = (
                    await self.session.get(Ticket, operation.ticket_id)
                    if operation.ticket_id
                    else None
                )
                if ticket:
                    failure.detail.outcome = "ticket_created"
                    failure.detail.ticket_code = ticket.code
                    failure.detail.message = f"工单 {ticket.code} 已创建，但回复或记录更新未完成。请到我的工单查看，不要重复提交。"
                elif not operation.write_started:
                    failure.detail.outcome = "not_executed"
                    failure.detail.retryable = (
                        failure.detail.code != "model_configuration"
                    )
                    failure.detail.message += "本次未执行建单操作。"
                else:
                    failure.detail.message += (
                        "建单结果尚需核对，请先查看我的工单，不要重复提交。"
                    )
                operation.status = "failed"
                operation.error = {
                    "detail": failure.detail.model_dump(mode="json"),
                    "status": failure.status_code,
                }
                await self.session.commit()
            except Exception:
                # 无法核对数据库时绝不声称没有建单；原 running 记录仍阻止重复执行。
                await self.session.rollback()
                logger.exception("agent_receipt_check_failed", operation_id=str(key))
                failure.detail.outcome = "unknown"
                failure.detail.retryable = False
                failure.detail.message = (
                    "暂时无法核对本次操作结果，请先查看我的工单，不要重复提交。"
                )
            raise failure from exc
