from functools import lru_cache
from typing import cast

from langchain_openai import ChatOpenAI

from app.agent.graph import ToolCallingModel, build_support_graph
from app.agent.schemas import AgentDecision
from app.agent.tools import create_support_ticket
from app.core.config import get_settings


class ModelConfigurationError(RuntimeError):
    """模型配置缺失时抛出，API 层会转换为可理解的服务错误。"""


@lru_cache
def get_support_graph():
    """延迟创建并缓存 Graph，避免应用启动时因缺少密钥直接失败。"""

    settings = get_settings()
    if not settings.model_api_key:
        raise ModelConfigurationError("未配置 SUPPORT_MODEL_API_KEY，无法调用客服 Agent")

    # 必须在创建模型和 Graph 前同步追踪配置，确保 LangChain 自动注册正确的 LangSmith 回调。
    settings.configure_langsmith_environment()

    # ChatOpenAI 同时兼容 OpenAI 及实现兼容接口的模型服务，便于后续切换供应商。
    model = ChatOpenAI(
        model=settings.model_name,
        api_key=settings.model_api_key,
        base_url=settings.model_base_url,
        temperature=0,
         # DeepSeek V4 默认启用思考模式，但强制 Function Calling 与该模式不兼容
        extra_body={"thinking": {"type": "disabled"}},
    )
    # 使用 DeepSeek 支持的 Function Calling 获取结构化结果，避免默认 response_format 导致 400。
    decision_model = model.with_structured_output(
        AgentDecision,
        method="function_calling",
    )
    # 业务 Tool 单独绑定到模型。只有 Graph 已确认建单意图后才调用该模型，
    # 避免普通咨询也携带可产生数据库副作用的工具选择机会。
    ticket_calling_model = model.bind_tools(
        [create_support_ticket],
        tool_choice=create_support_ticket.name,
    )
    return build_support_graph(
        decision_model,
        cast(ToolCallingModel, ticket_calling_model),
    )
