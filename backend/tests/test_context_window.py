"""上下文裁剪验证：模型看到窗口，检查点仍保留完整历史与业务状态。"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from app.agent.graph import build_support_graph
from app.agent.memory.context_window import (
    ContextWindowExceeded,
    ContextWindowPolicy,
    InvalidToolHistory,
    WindowedModel,
    prepare_model_messages,
)
from app.agent.memory.order_memory import OrderChoice, OrderMemory
from app.agent.schemas import AgentDecision


def policy(**overrides):
    return ContextWindowPolicy(
        **{"max_messages": 5, "max_tokens": 4096, "reserve_tokens": 0, **overrides}
    )


def test_last_messages_and_systems_are_preserved_without_mutation():
    systems = [SystemMessage(content="安全规则"), SystemMessage(content="已选择的订单")]
    history = [
        HumanMessage(content="旧问题"),
        AIMessage(content="旧回复"),
        HumanMessage(content="中间问题"),
        AIMessage(content="中间回复"),
        HumanMessage(content="当前问题"),
    ]
    source = systems + history
    result = prepare_model_messages(source, policy(max_messages=3))
    assert result == systems + history[-3:]
    assert source == systems + history


def test_token_budget_can_trim_below_message_limit():
    source = [
        HumanMessage(content="旧问题" * 800),
        AIMessage(content="旧回复"),
        HumanMessage(content="现在的问题"),
    ]
    assert prepare_model_messages(source, policy(max_tokens=512)) == source[-1:]


def test_current_tool_round_is_kept_whole():
    current = [
        HumanMessage(content="查订单"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "query_my_orders", "args": {}, "id": "a"},
                {"name": "query_my_orders", "args": {}, "id": "b"},
            ],
        ),
        ToolMessage(content="第一条结果", tool_call_id="a"),
        ToolMessage(content="第二条结果", tool_call_id="b"),
    ]
    source = [HumanMessage(content="旧问题"), AIMessage(content="旧回复"), *current]
    assert prepare_model_messages(source, policy(max_messages=4)) == current
    with pytest.raises(ContextWindowExceeded):
        prepare_model_messages(source, policy(max_messages=3))


@pytest.mark.parametrize(
    "history",
    [
        [
            HumanMessage(content="问题"),
            ToolMessage(content="孤立结果", tool_call_id="bad"),
        ],
        [
            HumanMessage(content="问题"),
            AIMessage(content="", tool_calls=[{"name": "tool", "args": {}, "id": "a"}]),
        ],
    ],
)
def test_invalid_tool_protocol_is_rejected(history):
    with pytest.raises(InvalidToolHistory):
        prepare_model_messages(history, policy())


def test_large_current_input_is_not_silently_truncated():
    message = HumanMessage(content="问题" * 2000)
    with pytest.raises(ContextWindowExceeded):
        prepare_model_messages([message], policy(max_tokens=512))
    assert message.content == "问题" * 2000


def test_system_only_creation_prompt_and_reserved_budget():
    assert prepare_model_messages([SystemMessage(content="建单指令")], policy())
    with pytest.raises(ContextWindowExceeded):
        prepare_model_messages(
            [SystemMessage(content="规则" * 2000)], policy(max_tokens=512)
        )
    with pytest.raises(ValidationError):
        policy(max_tokens=512, reserve_tokens=512)


def test_settings_accept_nested_environment(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("SUPPORT_CONTEXT_WINDOW__MAX_MESSAGES", "12")
    settings = Settings(_env_file=None)
    assert settings.context_window.max_messages == 12


def test_budget_error_has_explicit_feedback():
    from app.services.agent_errors import classify_agent_error

    failure = classify_agent_error(ContextWindowExceeded("too long"))
    assert failure.status_code == 413
    assert failure.detail.code == "context_window_exceeded"


@pytest.mark.asyncio
async def test_graph_checkpointer_keeps_full_history():
    original = [
        HumanMessage(content="旧问题"),
        AIMessage(content="旧回复"),
        HumanMessage(content="你好"),
    ]
    model = AsyncMock()
    model.ainvoke.return_value = AgentDecision(
        intent="general",
        priority="low",
        requires_human=False,
        should_create_ticket=False,
        needs_ticket_details=False,
        reason="普通问候",
        reply="您好",
    )
    saver = InMemorySaver()
    graph = build_support_graph(
        WindowedModel(model, policy(max_messages=1, max_tokens=20000)),
        checkpointer=saver,
    )
    config = {"configurable": {"thread_id": str(uuid4())}}
    memory = OrderMemory(
        stage="collect_issue", selected=OrderChoice(code="MO-a", product_name="键盘")
    )
    result = await graph.ainvoke({"messages": original, "order_memory": memory}, config)
    model_input = model.ainvoke.call_args.args[0]
    assert [m.content for m in model_input if isinstance(m, HumanMessage)] == ["你好"]
    assert model_input[0].type == model_input[1].type == "system"
    snapshot = await graph.aget_state(config)
    assert len(snapshot.values["messages"]) == 4
    assert snapshot.values["order_memory"].selected.code == "MO-a"
    assert result["executed_tool"] is None


@pytest.mark.asyncio
async def test_wrapper_does_not_call_model_when_current_round_too_large():
    model = AsyncMock()
    windowed = WindowedModel(model, policy(max_tokens=512))
    with pytest.raises(ContextWindowExceeded):
        await windowed.ainvoke([HumanMessage(content="很长的输入" * 1000)])
    model.ainvoke.assert_not_awaited()
