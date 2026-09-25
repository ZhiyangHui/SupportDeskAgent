"""补充工单的状态、Graph 与工具边界测试，不访问真实模型。"""

from uuid import uuid4

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.agent.memory.comment_memory import (
    CommentMemory,
    CommentTurn,
    advance_comment_memory,
)
from app.schema.ticket_comment import TicketCommentResult


def test_comment_memory_selection_cancel_and_unrelated_turn():
    original = CommentMemory(
        active=True, content="设备冒烟", candidates=["TK-b", "TK-a"]
    )
    selected = advance_comment_memory(
        original, CommentTurn(action="continue", reference="2"), ""
    )
    assert selected.reference == "TK-a" and selected.content == "设备冒烟"
    assert original.reference == ""
    invalid = advance_comment_memory(
        selected, CommentTurn(action="continue", reference="99"), ""
    )
    assert invalid.reference == "99"  # 无效选择不能沿用旧工单写入。
    assert advance_comment_memory(selected, CommentTurn(), "") == selected
    assert (
        advance_comment_memory(selected, CommentTurn(action="cancel"), "")
        == CommentMemory()
    )
    assert advance_comment_memory(selected, CommentTurn(action="new"), "").content == ""
    assert (
        advance_comment_memory(
            original, CommentTurn(action="continue", reference="last"), "TK-last"
        ).reference
        == "TK-last"
    )


def test_comment_state_can_roundtrip_checkpoint_serializer():
    """新增 Pydantic 状态必须可由官方序列化器恢复，不依赖 pickle。"""
    serde = JsonPlusSerializer(
        allowed_msgpack_modules=[CommentMemory, TicketCommentResult]
    )
    state = {
        "comment_memory": CommentMemory(
            active=True, content="设备冒烟", candidates=["TK-a"]
        ),
        "comment_result": TicketCommentResult(
            success=True,
            message="已补充",
            ticket_id=uuid4(),
            activity_id=uuid4(),
            ticket_code="TK-a",
        ),
    }
    restored = serde.loads_typed(serde.dumps_typed(state))
    assert restored == state
