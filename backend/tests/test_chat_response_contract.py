"""聊天接口必须与前端工具枚举一致；历史回执兼容只规范化已知的空字符串。"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schema.conversation import ChatResponse


def response_payload(executed_tool):
    return {
        "conversation_id": uuid4(),
        "customer_message_id": uuid4(),
        "agent_message_id": uuid4(),
        "agent_run_id": uuid4(),
        "reply": "王先生您好。",
        "reason": "普通问候",
        "intent": "general",
        "priority": "low",
        "requires_human": False,
        "executed_tool": executed_tool,
    }


@pytest.mark.parametrize("value", [None, ""])
def test_no_tool_serializes_as_null(value):
    assert (
        ChatResponse.model_validate(response_payload(value)).model_dump(mode="json")[
            "executed_tool"
        ]
        is None
    )


def test_unknown_tool_name_is_rejected():
    with pytest.raises(ValidationError):
        ChatResponse.model_validate(response_payload("invented_tool"))


@pytest.mark.parametrize(
    "name",
    [
        "query_my_orders",
        "create_order_ticket",
        "query_support_tickets",
        "create_support_ticket",
    ],
)
def test_known_tool_name_is_preserved(name):
    assert ChatResponse.model_validate(response_payload(name)).executed_tool == name
