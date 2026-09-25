"""补充工单的多轮草稿：只保存选择和待提交文本，不把历史成功当作新授权。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CommentTurn(BaseModel):
    """模型只抽取本轮意愿；身份、权限和最终写入由服务端控制。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["none", "new", "continue", "cancel"] = "none"
    reference: str = Field(
        default="",
        max_length=100,
        description="客户本轮提供的工单编号、标题关键词、候选序号；刚才那张填 last，未指定留空",
    )
    content: str = Field(
        default="",
        max_length=4000,
        description="客户本轮要补充的原意，不虚构事实；只有选择工单时留空",
    )


class CommentMemory(BaseModel):
    """由 Checkpointer 按会话持久化，客户先说内容再选编号也不会丢草稿。"""

    active: bool = False
    reference: str = ""
    content: str = ""
    # 顺序与实际展示列表一致，不能让模型重新排列后解释数字。
    candidates: list[str] = Field(default_factory=list)


def advance_comment_memory(
    memory: CommentMemory, turn: CommentTurn, last_code: str
) -> CommentMemory:
    """取消清空草稿，无关咨询保留草稿；新请求不继承上次成功的补充内容。"""
    if turn.action == "cancel":
        return CommentMemory()
    updated = (
        CommentMemory(active=True)
        if turn.action == "new"
        else memory.model_copy(deep=True)
    )
    if turn.action == "none":
        return updated
    updated.active = True
    if turn.content:
        updated.content = turn.content
    if turn.reference:
        reference = turn.reference
        if reference == "last":
            reference = last_code
        elif reference.isdecimal() and len(reference) <= 5:
            index = int(reference) - 1
            if 0 <= index < len(updated.candidates):
                reference = updated.candidates[index]
        updated.reference = reference
    return updated
