"""输出校验和安全错误分类回归，不使用真实模型或自动重试工具副作用。"""

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from app.agent.graph import build_support_graph
from app.agent.schemas import AgentDecision
from app.services.agent_errors import ModelOutputError, classify_agent_error


@pytest.mark.asyncio
async def test_bad_creation_arguments_are_corrected_once_before_any_write():
    decision = AgentDecision(
        intent="ticket",
        priority="low",
        requires_human=False,
        should_create_ticket=True,
        needs_ticket_details=False,
        ticket_title="登录异常",
        ticket_description="页面无法登录",
        reason="客户要求建单",
        reply="准备建单",
    )
    decider = AsyncMock()
    decider.ainvoke.return_value = decision
    caller = AsyncMock()
    caller.ainvoke.return_value = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "bad",
                "name": "create_support_ticket",
                "args": {"title": "模型擅自改写"},
            }
        ],
    )
    with pytest.raises(ModelOutputError):
        await build_support_graph(decider, caller).ainvoke(
            {"messages": [HumanMessage(content="建单")]}
        )
    assert caller.ainvoke.await_count == 2


@pytest.mark.parametrize(
    "error,code,status",
    [
        (TimeoutError("内部密钥不能回显"), "agent_timeout", 504),
        (ModelOutputError("内部数据"), "model_output_invalid", 502),
        (RuntimeError("私密内容"), "agent_failed", 502),
    ],
)
def test_error_classification_does_not_expose_raw_exception(error, code, status):
    result = classify_agent_error(error)
    assert result.detail.code == code
    assert result.status_code == status
    assert str(error) not in result.detail.message
    assert result.detail.outcome == "unknown"


@pytest.mark.asyncio
async def test_category_correction_includes_schema_without_raw_input():
    """非法分类应收到具体字段与合法枚举，而不是再次得到笼统的检查格式提示。"""

    fields = {
        "intent": "order",
        "priority": "high",
        "requires_human": False,
        "should_create_ticket": False,
        "needs_ticket_details": True,
        "reason": "还需了解退货问题",
        "reply": "订单 111 退货时遇到了什么问题？",
    }
    with pytest.raises(ValidationError) as captured:
        AgentDecision(**fields, ticket_category="private-invalid-category")
    model = AsyncMock()
    model.ainvoke.side_effect = [
        captured.value,
        AgentDecision(**fields, ticket_category="order"),
    ]
    result = await build_support_graph(model).ainvoke(
        {"messages": [HumanMessage(content="订单编号111，帮我创建工单")]}
    )
    correction = model.ainvoke.call_args.args[0][0].content
    assert '"field": "ticket_category"' in correction
    assert '"order"' in correction and '"billing"' in correction
    assert "private-invalid-category" not in correction
    assert result["needs_ticket_details"] is True
    assert model.ainvoke.await_count == 2
