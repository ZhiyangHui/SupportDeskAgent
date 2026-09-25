"""模型调用前的上下文窗口：使用官方 trim_messages，不修改 Checkpointer 中的历史。"""

from collections.abc import Sequence
from typing import Generic, Protocol, TypeVar

import structlog
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    trim_messages,
)
from langchain_core.messages.utils import count_tokens_approximately
from pydantic import BaseModel, Field, model_validator


class ContextWindowPolicy(BaseModel):
    """限制模型可见输入，而不是删除数据库记录；Token 为估算值，并非供应商精确计费。"""

    max_messages: int = Field(default=40, ge=1, le=200)
    max_tokens: int = Field(default=12000, ge=512, le=1000000)
    reserve_tokens: int = Field(default=2048, ge=0)
    chars_per_token: float = Field(default=2.0, gt=0, le=4)

    @model_validator(mode="after")
    def validate_reserve(self) -> "ContextWindowPolicy":
        if self.reserve_tokens >= self.max_tokens:
            raise ValueError("预留 Token 必须小于模型输入窗口预算")
        return self


class ContextWindowExceeded(RuntimeError):
    """系统指令和当前完整轮次已超预算，不能靠截断诉求或工具 JSON 强行发送。"""


class InvalidToolHistory(RuntimeError):
    """工具调用与结果不成对，应检查流程记录，不能发给模型继续猜测。"""


def prepare_model_messages(
    messages: Sequence[BaseMessage], policy: ContextWindowPolicy
) -> list[BaseMessage]:
    """保留前置系统消息和最近完整轮次；只返回新列表，不回写 Graph State。"""
    source = list(messages)
    split = 0
    while split < len(source) and isinstance(source[split], SystemMessage):
        split += 1
    systems, history = source[:split], source[split:]

    def count(items: Sequence[BaseMessage]) -> int:
        # 中文对默认字符比例较敏感，使用可配置的保守估算；不宣称精确满足供应商上限。
        return count_tokens_approximately(items, chars_per_token=policy.chars_per_token)

    available = policy.max_tokens - policy.reserve_tokens
    budget = available - count(systems)
    if budget < 0:
        raise ContextWindowExceeded("系统指令超过上下文预算")
    # 普通建单节点只传系统指令。这类调用也计预算，但不能凭空补一条客户消息。
    if not history:
        return systems

    human_indices = [
        i for i, item in enumerate(history) if isinstance(item, HumanMessage)
    ]
    if not human_indices:
        raise InvalidToolHistory("模型历史缺少客户消息")
    mandatory = history[human_indices[-1] :]
    if len(mandatory) > policy.max_messages or count(mandatory) > budget:
        raise ContextWindowExceeded("当前完整轮次超过上下文预算")

    # 先控制条数，再按 Token 裁剪；start_on 保证不会从孤立工具结果开始。
    selected = trim_messages(
        history,
        max_tokens=policy.max_messages,
        token_counter=len,
        strategy="last",
        start_on="human",
        allow_partial=False,
    )
    selected = trim_messages(
        selected,
        max_tokens=budget,
        token_counter=count,
        strategy="last",
        start_on="human",
        allow_partial=False,
    )
    if len(selected) < len(mandatory) or selected[-len(mandatory) :] != mandatory:
        raise ContextWindowExceeded("裁剪不能丢失当前客户输入或工具结果")

    # 本项目允许工具循环，也检查多工具结果的配对；不截断或修补工具调用参数。
    pending: set[str] = set()
    for item in selected:
        if isinstance(item, ToolMessage):
            if item.tool_call_id not in pending:
                raise InvalidToolHistory("工具结果缺少对应调用或重复返回")
            pending.remove(item.tool_call_id)
            continue
        if pending:
            raise InvalidToolHistory("工具调用尚未获得全部结果")
        if isinstance(item, SystemMessage):
            raise InvalidToolHistory("业务历史中不应插入系统指令")
        if isinstance(item, AIMessage) and item.tool_calls:
            identifiers: list[str] = []
            for call in item.tool_calls:
                identifier = call["id"]
                if not identifier:
                    raise InvalidToolHistory("工具调用缺少 ID")
                identifiers.append(identifier)
            if len(set(identifiers)) != len(identifiers):
                raise InvalidToolHistory("工具调用 ID 重复")
            pending.update(identifiers)
    if pending:
        raise InvalidToolHistory("不能在工具结果返回前继续调用模型")

    result = [*systems, *selected]
    if count(result) > available:
        raise ContextWindowExceeded("裁剪后的输入仍超过上下文预算")
    if len(selected) < len(history):
        # 只记录数量，不记录消息内容、订单号或客户身份。
        structlog.get_logger(__name__).info(
            "model_context_trimmed",
            messages_before=len(history),
            messages_after=len(selected),
            estimated_tokens=count(result),
            input_budget=available,
        )
    return result


Output_co = TypeVar("Output_co", covariant=True)


class AsyncMessageModel(Protocol[Output_co]):
    """兼容现有 Graph 使用的 ainvoke 协议，不接管模型重试、工具绑定或网络配置。"""

    async def ainvoke(self, input: list[BaseMessage]) -> Output_co: ...


class WindowedModel(Generic[Output_co]):
    """在已完成工具绑定或结构化输出配置的模型外统一裁剪，覆盖每次模型调用及纠正重试。"""

    def __init__(
        self, model: AsyncMessageModel[Output_co], policy: ContextWindowPolicy
    ):
        self.model = model
        self.policy = policy

    async def ainvoke(self, input: list[BaseMessage]) -> Output_co:
        return await self.model.ainvoke(prepare_model_messages(input, self.policy))
