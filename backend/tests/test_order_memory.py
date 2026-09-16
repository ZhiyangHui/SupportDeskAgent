"""售后记忆的纯状态测试，不调用模型和数据库。"""

from app.agent.order_memory import (
    OrderChoice,
    OrderMemory,
    OrderTurn,
    advance_order_memory,
)


def test_selection_then_issue_keeps_display_order():
    """数字以实际展示列表为准，后补诉求不能覆盖已选订单。"""
    choices = [
        OrderChoice(code="MO-b", product_name="维护服务"),
        OrderChoice(code="MO-a", product_name="键盘"),
    ]
    memory = OrderMemory(stage="select_order", candidates=choices)
    selected = advance_order_memory(memory, OrderTurn(action="continue", reference="1"))
    assert selected.selected == choices[0] and selected.stage == "collect_issue"
    ready = advance_order_memory(selected, OrderTurn(action="continue", issue="维修"))
    assert ready.selected == choices[0] and ready.stage == "ready"
    assert memory.selected is None  # 更新不能原地污染旧快照。


def test_issue_before_selection_and_invalid_choice():
    """客户可先给诉求；无效选择不能沿用旧订单直接写入。"""
    item = OrderChoice(code="MO-a", product_name="键盘")
    memory = OrderMemory(stage="collect_issue", candidates=[item], selected=item)
    invalid = advance_order_memory(
        memory, OrderTurn(action="continue", reference="99", issue="退款")
    )
    assert invalid.selected is None and invalid.issue == "退款"
    assert invalid.stage == "select_order"
    fixed = advance_order_memory(invalid, OrderTurn(action="continue", reference="1"))
    assert fixed.stage == "ready" and fixed.issue == "退款"


def test_cancel_and_restart_clear_previous_selection():
    """取消与重新开始都不能继承上一工单的选择或诉求。"""
    item = OrderChoice(code="MO-a", product_name="键盘")
    memory = OrderMemory(stage="ready", candidates=[item], selected=item, issue="维修")
    cancelled = advance_order_memory(memory, OrderTurn(action="cancel"))
    assert cancelled.stage == "cancelled" and not cancelled.active
    assert (
        not cancelled.candidates and cancelled.selected is None and not cancelled.issue
    )
    restarted = advance_order_memory(memory, OrderTurn(action="new"))
    assert (
        restarted.stage == "select_order"
        and not restarted.issue
        and restarted.selected is None
    )
