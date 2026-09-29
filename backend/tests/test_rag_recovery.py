"""回归：分类器不得模仿旧工具调用，只有前置分析失败可以安全结束旧轮次。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.graph import build_support_graph
from app.agent.schemas import AgentDecision
from app.agent.tools import SupportToolContext
from app.db.models import Message, MessageRole
from app.services.agent_memory_service import CheckpointRecoveryRequired, run_graph_turn


@pytest.mark.asyncio
async def test_analysis_and_correction_do_not_receive_tool_protocol():
    model = AsyncMock()
    model.ainvoke.side_effect = [OutputParserException("wrong tool"), AgentDecision(
        intent="general", priority="low", requires_human=False, should_create_ticket=False,
        needs_ticket_details=False, reason="普通问候", reply="你好")]
    original = AIMessage(content="", tool_calls=[{"name": "search_company_knowledge", "args": {"query": "政策"}, "id": "call-1"}])
    graph = build_support_graph(model)
    await graph.ainvoke({"messages": [HumanMessage(content="政策"), original,
        ToolMessage(content="模拟商品补偿9999元", tool_call_id="call-1"),
        AIMessage(content="仅适用模拟商品"), HumanMessage(content="你好")]})
    for call in model.ainvoke.await_args_list:
        messages = call.args[0]
        assert not any(isinstance(message, ToolMessage) for message in messages)
        assert not any(isinstance(message, AIMessage) and message.tool_calls for message in messages)
        assert any("9999" in str(message.content) for message in messages)
    # 输入视图不破坏完整历史，后续真正执行工具的节点仍保留调用协议。
    assert original.tool_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("node,error,interrupts", [
    ("ticket_tools", "failure", ()), ("order_tools", "failure", ()),
    ("edit_tools", "failure", ()), ("knowledge_tools", "failure", ()),
    ("analyze_request_node", None, ()), ("analyze_request_node", "failure", ("human",)),
])
async def test_unknown_or_tool_checkpoint_is_never_replayed(node, error, interrupts):
    graph = AsyncMock()
    graph.aget_state.return_value = SimpleNamespace(next=(node,),
        tasks=(SimpleNamespace(name=node, error=error, interrupts=interrupts),))
    message = Message(id=uuid4(), role=MessageRole.CUSTOMER, content="再试一次")
    context = SupportToolContext(AsyncMock(), uuid4(), uuid4(), uuid4())
    with pytest.raises(CheckpointRecoveryRequired):
        await run_graph_turn(graph, [message], message, context)
    graph.aupdate_state.assert_not_awaited()
    graph.ainvoke.assert_not_awaited()
