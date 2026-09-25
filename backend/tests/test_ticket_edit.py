"""修改工单必须经过选择和确认；用模型/数据库替身验证节点，不依赖付费 API。"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from app.agent.graph import build_support_graph
from app.agent.memory.persistence import create_memory_serializer
from app.agent.memory.ticket_edit_memory import (
    TicketEditMemory,
    TicketEditTurn,
    advance_ticket_edit,
)
from app.agent.schemas import AgentDecision
from app.agent.tools import SupportToolContext, update_support_ticket
from app.schema.ticket_edit import (
    CustomerTicketSnapshot,
    TicketChanges,
    TicketEditInput,
    TicketEditResult,
)
from app.schema.ticket_query import TicketQueryItem, TicketQueryResult


def edit_decision(action="continue", reference="", **changes):
    return AgentDecision(
        intent="ticket",
        priority="medium",
        requires_human=False,
        should_create_ticket=False,
        needs_ticket_details=False,
        reason="修改已有工单",
        reply="准备修改",
        edit_turn=TicketEditTurn(
            action=action, reference=reference, changes=TicketChanges(**changes)
        ),
    )


def test_edit_schema_and_state_boundaries():
    with pytest.raises(ValidationError):
        TicketChanges.model_validate({"priority": "urgent"})
    with pytest.raises(ValidationError):
        TicketEditInput(ticket_code="TK-a", expected_version=1, changes=TicketChanges())
    with pytest.raises(ValidationError):
        TicketChanges(title=" ")
    schema = update_support_ticket.tool_call_schema.model_json_schema()
    assert set(schema["properties"]) == {"ticket_code", "expected_version", "changes"}
    original = TicketEditMemory(
        stage="confirm",
        reference="TK-a",
        candidates=["TK-a"],
        changes=TicketChanges(desired_resolution="维修"),
        version=1,
    )
    changed = advance_ticket_edit(
        original,
        TicketEditTurn(
            action="confirm", changes=TicketChanges(desired_resolution="退款")
        ),
        "",
    )
    assert not changed.confirmed and changed.stage == "edit"
    assert not advance_ticket_edit(original, TicketEditTurn(action="cancel"), "").active
    swapped = advance_ticket_edit(
        original, TicketEditTurn(action="continue", reference="TK-b"), ""
    )
    assert swapped.stage == "select" and not swapped.changes.patch()
    serde = create_memory_serializer()
    assert serde.loads_typed(serde.dumps_typed(original)) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 2])
async def test_select_preview_confirm_real_tool_and_reset(monkeypatch, count):
    items = [
        TicketQueryItem(
            code=f"TK-{i}",
            title="退款工单",
            status="open",
            updated_at=datetime.now(UTC),
        )
        for i in range(count)
    ]
    query = AsyncMock(return_value=TicketQueryResult(items=items))
    monkeypatch.setattr(
        "app.agent.workflows.ticket_edit_workflow.TicketQueryService.search", query
    )
    snapshot = CustomerTicketSnapshot(
        order={"code": "MO-test", "product_name": "年度维护服务"},
        code="TK-0",
        version=1,
        status="open",
        title="退款工单",
        description="设备故障",
        desired_resolution="退款",
        impact_note="",
    )
    reader = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(
        "app.agent.workflows.ticket_edit_workflow.TicketEditService.snapshot", reader
    )
    writer = AsyncMock(
        return_value=TicketEditResult(
            success=True,
            changed=True,
            message="已修改",
            ticket_code="TK-0",
            ticket_id=uuid4(),
            activity_id=uuid4(),
        )
    )
    monkeypatch.setattr("app.agent.tools.TicketEditService.update", writer)
    model = AsyncMock()
    graph = build_support_graph(model, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": str(uuid4())}}
    context = SupportToolContext(AsyncMock(), uuid4(), uuid4(), uuid4(), uuid4())

    async def say(text):
        return await graph.ainvoke(
            {"messages": [HumanMessage(content=text)]}, config, context=context
        )

    result = await say("帮我跟进工单")
    assert "请选择" in result["final_reply"] and "待处理" in result["final_reply"]
    reader.assert_not_awaited()
    writer.assert_not_awaited()
    result = await say("1")
    assert "关联订单（只读）" in result["final_reply"]
    assert "商品：年度维护服务" in result["final_reply"]
    assert "订单号：MO-test" in result["final_reply"]
    assert (
        "当前可修改信息" in result["final_reply"]
        and "售后诉求：退款" in result["final_reply"]
    )
    writer.assert_not_awaited()
    model.ainvoke.return_value = edit_decision(
        desired_resolution="维修", description="设备开机会冒烟"
    )
    result = await say("改成维修，设备开机会冒烟")
    assert "退款 → 维修" in result["final_reply"]
    writer.assert_not_awaited()
    # 供应商误判确认也不能绕过本轮精确确认文本。
    model.ainvoke.return_value = edit_decision(action="confirm")
    await say("再让我看看")
    writer.assert_not_awaited()
    result = await say("确认修改")
    writer.assert_awaited_once()
    data = writer.call_args.args[2]
    assert data.changes.patch() == {
        "description": "设备开机会冒烟",
        "desired_resolution": "维修",
    }
    assert data.expected_version == 1
    assert (
        result["executed_tool"] == "update_support_ticket"
        and result["created_ticket_id"] is None
    )
    assert any(isinstance(item, ToolMessage) for item in result["messages"])
    model.ainvoke.return_value = edit_decision(action="none")
    result = await say("谢谢")
    assert result["edit_result"] is None and result["executed_tool"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status,version", [("closed", 1), ("open", 2)])
async def test_closed_and_stale_confirmation_do_not_write(monkeypatch, status, version):
    reader = AsyncMock(
        return_value=CustomerTicketSnapshot(
            code="TK-a",
            version=version,
            status=status,
            title="标题",
            description="描述",
            desired_resolution="退款",
            impact_note="",
        )
    )
    monkeypatch.setattr(
        "app.agent.workflows.ticket_edit_workflow.TicketEditService.snapshot", reader
    )
    writer = AsyncMock()
    monkeypatch.setattr("app.agent.tools.TicketEditService.update", writer)
    memory = TicketEditMemory(
        stage="confirm",
        reference="TK-a",
        changes=TicketChanges(desired_resolution="维修"),
        version=1,
    )
    result = await build_support_graph(AsyncMock()).ainvoke(
        {"messages": [HumanMessage(content="确认修改")], "edit_memory": memory},
        context=SupportToolContext(AsyncMock(), uuid4()),
    )
    assert ("已关闭" if status == "closed" else "重新确认") in result["final_reply"]
    writer.assert_not_awaited()
