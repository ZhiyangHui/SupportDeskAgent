from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.factory import ModelConfigurationError
from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    MessageResponse,
    MessageToolCallResponse,
)
from app.core.config import get_settings
from app.db.conversation_repository import ConversationNotFoundError
from app.db.session import get_db_session
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
) -> ChatResponse:
    """持久化客户消息，携带历史运行 Agent，再保存最终回复。"""

    service = ConversationService(session)
    try:
        result = await service.chat(request.message, request.conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在") from exc
    except ModelConfigurationError as exc:
        logger.warning("agent_model_configuration_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "agent_execution_failed",
            error_type=type(exc).__name__,
            upstream_status_code=getattr(exc, "status_code", None),
            conversation_id=str(request.conversation_id) if request.conversation_id else None,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="客服 Agent 暂时无法完成请求，请稍后重试",
        ) from exc

    # API 层显式映射 Service 返回值，不依赖 dataclass 的内部存储方式。
    return ChatResponse(
        conversation_id=result.conversation_id,
        customer_message_id=result.customer_message_id,
        agent_message_id=result.agent_message_id,
        reply=result.reply,
        intent=result.intent,
        priority=result.priority,
        requires_human=result.requires_human,
        reason=result.reason,
        created_ticket_id=result.created_ticket_id,
        created_ticket_code=result.created_ticket_code,
    )


@router.get(
    "/api/v1/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
    tags=["会话"],
)
async def list_conversation_messages(
    conversation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[MessageResponse]:
    """按稳定顺序返回会话历史，供页面刷新后恢复上下文。"""

    try:
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
                    ticket_code=message.tool_payload["ticket_code"],
                )
                if message.tool_name and message.tool_payload
                else None
            ),
        )
        for message in messages
    ]
