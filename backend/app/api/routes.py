from fastapi import APIRouter, HTTPException, status
from langchain_core.messages import HumanMessage

from app.agent.factory import ModelConfigurationError, get_support_graph
from app.api.schemas import ChatRequest, ChatResponse, HealthResponse
from app.core.config import get_settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["系统"])
async def health_check() -> HealthResponse:
    """提供给本地开发、容器和部署平台使用的轻量健康检查。"""

    settings = get_settings()
    return HealthResponse(status="ok", service=settings.app_name, version=settings.app_version)


@router.post("/api/v1/agent/chat", response_model=ChatResponse, tags=["Agent"])
async def chat_with_agent(request: ChatRequest) -> ChatResponse:
    """运行一次客服 Graph，并将内部状态收敛成稳定的 API 响应。"""

    try:
        graph = get_support_graph()
        result = await graph.ainvoke({"messages": [HumanMessage(content=request.message)]})
    except ModelConfigurationError as exc:
        # 配置问题属于服务暂不可用，不应伪装成用户输入错误或返回虚假回复。
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        # 第一版不向客户端暴露供应商错误和内部调用栈，详细信息后续交给结构化日志记录。
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="客服 Agent 暂时无法完成请求，请稍后重试",
        ) from exc

    return ChatResponse(
        reply=result["final_reply"],
        intent=result["intent"],
        priority=result["priority"],
        requires_human=result["requires_human"],
        reason=result["decision_reason"],
    )
