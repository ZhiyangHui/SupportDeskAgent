"""客户修改工单的短期状态：明确区分选择、编辑与确认，确认只对当前草稿有效。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schema.ticket_edit import TicketChanges


class TicketEditTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["none", "new", "continue", "confirm", "cancel"] = "none"
    reference: str = Field(
        default="",
        max_length=100,
        description="本轮工单编号、标题关键词或列表序号；刚才那张填 last，未指定留空",
    )
    changes: TicketChanges = Field(
        default_factory=TicketChanges,
        description="仅填写本轮明确要修改的字段，未提及为 null；不能从历史虚构变更",
    )


class TicketEditMemory(BaseModel):
    stage: Literal["idle", "select", "edit", "confirm", "done"] = "idle"
    reference: str = ""
    candidates: list[str] = Field(default_factory=list)
    changes: TicketChanges = Field(default_factory=TicketChanges)
    version: int | None = None
    confirmed: bool = False

    @property
    def active(self) -> bool:
        return self.stage in {"select", "edit", "confirm"}


def advance_ticket_edit(
    memory: TicketEditMemory, turn: TicketEditTurn, last_code: str
) -> TicketEditMemory:
    if turn.action == "cancel":
        return TicketEditMemory()
    result = memory.model_copy(deep=True)
    result.confirmed = False  # 不能把上一轮确认带入新请求或更改后的草稿。
    if turn.action == "none":
        return result
    if turn.action == "new" or not memory.active:
        result = TicketEditMemory(stage="select")
    reference = last_code if turn.reference == "last" else turn.reference
    if reference:
        if reference.isdecimal() and len(reference) <= 5:
            index = int(reference) - 1
            reference = (
                result.candidates[index]
                if 0 <= index < len(result.candidates)
                else reference
            )
        if result.stage == "select" and reference in result.candidates:
            result.stage = "edit"
        elif reference != result.reference:
            # 换目标必须重新展示候选；已选择工单的草稿不能无声转移到另一张工单。
            if result.stage in {"edit", "confirm"}:
                result.changes = TicketChanges()
            result.stage, result.candidates, result.version = "select", [], None
        result.reference = reference
    patch = turn.changes.patch()
    if patch:
        result.changes = TicketChanges.model_validate(
            {**result.changes.patch(), **patch}
        )
        if result.stage == "confirm":
            result.stage = "edit"
    if (
        turn.action == "confirm"
        and result.stage == "confirm"
        and not patch
        and not turn.reference
    ):
        result.confirmed = True
    return result
