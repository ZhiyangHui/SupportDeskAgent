"""售后会话的结构化短期记忆：保存业务步骤，不把模型措辞当作订单确认。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OrderChoice(BaseModel):
    """候选的排列顺序就是展示顺序；UUID 仍由本轮查询验证后用于写入。"""

    code: str
    product_name: str


class OrderTurn(BaseModel):
    """模型仅抽取本轮变化，不能直接设置已选 UUID 或伪造候选。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["continue", "cancel", "new", "none"] = "none"
    reference: str = Field(
        default="",
        max_length=100,
        description="本轮明确选择的序号、订单号或商品名；未提及则为空",
    )
    issue: str = Field(
        default="",
        max_length=2000,
        description="客户明确表达的售后诉求，如维修；不得把序号当作诉求，不得虚构",
    )


class OrderMemory(BaseModel):
    """同一会话的售后草稿，成功回复时保存；完成和取消后不继承旧授权。"""

    version: Literal[1] = 1
    stage: Literal[
        "idle", "select_order", "collect_issue", "ready", "completed", "cancelled"
    ] = "idle"
    candidates: list[OrderChoice] = Field(default_factory=list)
    selected: OrderChoice | None = None
    reference: str = ""
    issue: str = ""

    @property
    def active(self) -> bool:
        return self.stage in {"select_order", "collect_issue", "ready"}


def advance_order_memory(memory: OrderMemory, turn: OrderTurn) -> OrderMemory:
    """只应用明确的新信息，序号必须对应上次展示的列表，不能交给模型重排。"""

    if turn.action == "cancel":
        return OrderMemory(stage="cancelled")
    result = (
        memory.model_copy(deep=True)
        if memory.active and turn.action != "new"
        else OrderMemory(stage="select_order")
    )
    if turn.reference:
        reference = turn.reference.strip()
        # 新选择使原选择失效；非法序号保留列表供再次展示，绝不沿用原订单写入。
        result.selected = None
        result.reference = reference
        if reference.isdecimal():
            index = int(reference) - 1
            if 0 <= index < len(result.candidates):
                result.selected = result.candidates[index]
        else:
            matches = [
                item
                for item in result.candidates
                if reference in (item.code, item.product_name)
            ]
            if len(matches) == 1:
                result.selected = matches[0]
    if turn.issue:
        result.issue = turn.issue
    result.stage = (
        "select_order"
        if not result.selected
        else "ready"
        if result.issue
        else "collect_issue"
    )
    return result
