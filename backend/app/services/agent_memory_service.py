"""会话与官方检查点的边界：稳定消息 ID、旧会话首次导入、失败执行保护。"""

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from app.agent.order_memory import OrderMemory
from app.agent.state import SupportAgentState
from app.agent.tools import SupportToolContext
from app.db.models import Message, MessageRole


class CheckpointRecoveryRequired(RuntimeError):
    """未完成图可能已有业务副作用，不能借新消息盲目续跑。"""


def conversation_config(context: SupportToolContext) -> RunnableConfig:
    # 身份取自认证和业务会话，禁止直接采用客户端传入的 thread_id。
    return {
        "configurable": {
            "thread_id": f"{context.company_id}:{context.customer_id}:{context.conversation_id}"
        }
    }


async def run_graph_turn(
    graph: CompiledStateGraph[SupportAgentState, SupportToolContext, Any, Any],
    history: list[Message],
    current: Message,
    context: SupportToolContext,
) -> dict[str, Any]:
    """已有检查点只追加本轮 HumanMessage，旧数据库历史不反复拼回 messages。"""
    if graph.checkpointer is None:
        raise RuntimeError("会话 Graph 必须配置 Checkpointer")
    config = conversation_config(context)
    snapshot = await graph.aget_state(config)
    if snapshot.next:
        raise CheckpointRecoveryRequired(
            "上一轮检查点尚未完成，请核对请求回执后恢复，不能自动重放工具"
        )
    message = HumanMessage(content=current.content, id=str(current.id))
    inputs: dict[str, Any] = {"messages": [message]}
    if not snapshot.values:
        # 兼容历史会话：仅无检查点时导入一次。消息 ID 使用业务主键，符合 add_messages 去重语义。
        inputs["messages"] = [
            HumanMessage(content=item.content, id=str(item.id))
            if item.role == MessageRole.CUSTOMER
            else AIMessage(content=item.content, id=str(item.id))
            for item in history
        ]
        previous = next(
            (item for item in reversed(history) if item.role == MessageRole.AGENT), None
        )
        legacy = (previous.tool_payload or {}).get("order_memory") if previous else None
        inputs["order_memory"] = (
            OrderMemory.model_validate_json(legacy) if legacy else OrderMemory()
        )
    return await graph.ainvoke(
        inputs, config=config, context=context, durability="sync"
    )
