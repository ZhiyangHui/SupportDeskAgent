"""订单描述整理遵循精确匹配，不覆盖含否定或复杂诉求的客户原文。"""

import pytest
from pydantic import ValidationError

from app.schema.ticket_edit import TicketChanges
from app.services.ticket_content import split_order_issue


@pytest.mark.parametrize("text", ["维修", "希望退款", "申请换货", "我要退货退款"])
def test_simple_resolution_is_separate(text):
    assert split_order_issue(text) == ("", text)


@pytest.mark.parametrize("text", ["机械故障，希望维修", "不退款，只维修", "维修后仍然无法启动"])
def test_complex_issue_is_preserved(text):
    assert split_order_issue(text) == (text, "")


def test_order_is_not_customer_editable():
    with pytest.raises(ValidationError):
        TicketChanges.model_validate({"order": {"code": "MO-other"}})
