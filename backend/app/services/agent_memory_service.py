"""会话与官方检查点的边界：稳定消息 ID、旧会话首次导入、失败执行保护。"""

from typing import Any

import structlog
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot

from app.agent.memory.order_memory import OrderMemory
from app.agent.state import SupportAgentState
from app.agent.tools import SupportToolContext
from app.db.models import Message, MessageRole


class CheckpointRecoveryRequired(RuntimeError):
    """未完成图可能已有业务副作用，不能借新消息盲目续跑。"""


def can_close_failed_analysis(snapshot: StateSnapshot) -> bool:
    """只放行确定失败的前置意图节点；中断、未知节点和任何工具阶段均保持保护。"""
    return (
        snapshot.next == ("analyze_request_node",)
        and len(snapshot.tasks) == 1
        and snapshot.tasks[0].name == "analyze_request_node"
        and bool(snapshot.tasks[0].error)
        and not snapshot.tasks[0].interrupts
    )


def conversation_config(context: SupportToolContext) -> RunnableConfig:
    # 身份取自认证和业务会话，禁止直接采用客户端传入的 thread_id。
    # 人工恢复后启用新检查点，从业务历史导入人工对话，不续跑旧的待确认写操作。
    suffix = f":resume:{context.memory_generation}" if context.memory_generation else ""
    return {
        "configurable": {
            "thread_id": f"{context.company_id}:{context.customer_id}:{context.conversation_id}{suffix}"
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
    if can_close_failed_analysis(snapshot):
        # 此节点位于工具执行之前，失败时尚未提交本轮决策。使用官方状态更新关闭
        # 失败轮次，而非 ainvoke(None) 续跑旧输入；新消息仍从 START 重新判断。
        await graph.aupdate_state(config, {
            "messages": [AIMessage(content="上一轮意图分析失败，该轮未执行业务工具。")],
            "final_reply": "", "knowledge_hits": [], "knowledge_error": "",
        }, as_node="automatic_reply_node")
        structlog.get_logger(__name__).info("failed_analysis_checkpoint_closed", node="analyze_request_node")
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
        legacy = (previous.tool_payload or {}).get("order_memory") if previous and not context.memory_generation else None
        inputs["order_memory"] = (
            OrderMemory.model_validate_json(legacy) if legacy else OrderMemory()
        )
    return await graph.ainvoke(
        inputs, config=config, context=context, durability="sync"
    )
