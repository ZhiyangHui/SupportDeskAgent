from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import customer_identity
from app.core.config import get_settings
from app.db.conversation_repository import (
    ConversationNotFoundError,
    ConversationRepository,
)
from app.db.session import get_db_session
from app.schema.access import Principal
from app.schema.agent_error import AgentRequestError
from app.schema.conversation import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    MessageResponse,
    MessageToolCallResponse,
)
from app.services.agent_errors import classify_agent_error
from app.services.chat_request_service import ChatRequestService
from app.services.conversation_service import ConversationService

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/health", response_model=HealthResponse, tags=["系统"])
async def health_check() -> HealthResponse:
    """轻量健康检查不访问数据库和模型，避免外部故障掩盖 API 进程状态。"""

    settings = get_settings()
    return HealthResponse(status="ok", service=settings.app_name, version=settings.app_version)


@router.post("/api/v1/agent/chat", response_model=ChatResponse, tags=["Agent"])
async def chat_with_agent(
    request: ChatRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    customer: Annotated[Principal, Depends(customer_identity)],
) -> ChatResponse:
    """持久化客户消息，携带历史运行 Agent，再保存最终回复。"""

    try:
        return await ChatRequestService(session).chat(request, customer)
    except AgentRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail.model_dump(mode="json")) from exc
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在") from exc
    except Exception as exc:
        logger.exception(
            "agent_execution_failed",
            error_type=type(exc).__name__,
            upstream_status_code=getattr(exc, "status_code", None),
            conversation_id=str(request.conversation_id) if request.conversation_id else None,
        )
        failure = classify_agent_error(exc)
        failure.detail.message += "暂时无法核对操作结果，请先查看我的工单，不要重复建单。"
        raise HTTPException(status_code=failure.status_code, detail=failure.detail.model_dump(mode="json")) from exc

@router.get(
    "/api/v1/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
    tags=["会话"],
)
async def list_conversation_messages(
    conversation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    customer: Annotated[Principal, Depends(customer_identity)],
) -> list[MessageResponse]:
    """按稳定顺序返回会话历史，供页面刷新后恢复上下文。"""

    try:
        conversation = await ConversationRepository(session).get_conversation(conversation_id)
        if conversation.customer_id != customer.id:
            raise ConversationNotFoundError("会话不存在")
        messages = await ConversationService(session).list_messages(conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在") from exc

    return [
        MessageResponse(
            id=message.id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            tool_call=(
                MessageToolCallResponse(
                    name=message.tool_name,
                    status=message.tool_payload["status"],
                    ticket_code=message.tool_payload.get("ticket_code"),
                )
                if message.tool_name and message.tool_payload
                else None
            ),
        )
        for message in messages
    ]
