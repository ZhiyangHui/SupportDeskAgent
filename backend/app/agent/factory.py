from functools import lru_cache
from typing import cast

from langchain_openai import ChatOpenAI

from app.agent.graph import ToolCallingLLM, build_support_graph
from app.agent.schemas import AgentDecision
from app.agent.tools import (
    create_order_ticket,
    create_support_ticket,
    query_my_orders,
    query_support_tickets,
)
from app.core.config import get_settings


class ModelConfigurationError(RuntimeError):
    """模型配置缺失时抛出，API 层会转换为可理解的服务错误。"""


@lru_cache
def get_support_graph():
    """延迟创建并缓存 Graph，避免应用启动时因缺少密钥直接失败。"""

    settings = get_settings()
    from app.agent.persistence import get_memory_resources
    resources = get_memory_resources()
    if not settings.model_api_key:
        raise ModelConfigurationError(
            "未配置 SUPPORT_MODEL_API_KEY，无法调用客服 Agent"
        )

    # 必须在创建模型和 Graph 前同步追踪配置，确保 LangChain 自动注册正确的 LangSmith 回调。
    settings.configure_langsmith_environment()

    # llm_client 是连接模型服务的客户端，不是 Graph 节点，也不是另一个独立部署的模型。
    # 下方 *_llm 是在同一客户端上配置输出格式或可用工具后的调用对象。
    llm_client = ChatOpenAI(
        model=settings.model_name,
        api_key=settings.model_api_key,
        base_url=settings.model_base_url,
        temperature=0,
        timeout=30,
        # 只在 Graph 中纠正格式错误，避免 SDK 隐式重试叠加工作流的时间预算。
        max_retries=0,
        # DeepSeek V4 默认启用思考模式，但强制 Function Calling 与该模式不兼容
        extra_body={"thinking": {"type": "disabled"}},
    )
    # 使用 DeepSeek 支持的 Function Calling 获取结构化结果，避免默认 response_format 导致 400。
    decision_llm = llm_client.with_structured_output(
        AgentDecision,
        method="function_calling",
    )
    # 业务 Tool 单独绑定到模型。只有 Graph 已确认建单意图后才调用该模型，
    # 避免普通咨询也携带可产生数据库副作用的工具选择机会。
    ticket_creation_llm = llm_client.bind_tools(
        [create_support_ticket],
        tool_choice=create_support_ticket.name,
    )
    # 查询分支仅提供只读工具，保留自动选择，让模型查询后可以直接回复而非被迫再次调用工具。
    ticket_query_llm = llm_client.bind_tools(
        [query_support_tickets],
    )
    order_llm = llm_client.bind_tools([query_my_orders, create_order_ticket])
    return build_support_graph(
        decision_llm,
        cast(ToolCallingLLM, ticket_creation_llm),
        cast(ToolCallingLLM, ticket_query_llm),
        cast(ToolCallingLLM, order_llm),
        checkpointer=resources.checkpointer,
        store=resources.store,
    )
