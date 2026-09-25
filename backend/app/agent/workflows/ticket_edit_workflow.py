"""跟进工单工作流：展示候选→选择→展示可编辑信息→预览→客户确认→真实工具。"""

import asyncio
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from app.agent.state import SupportAgentState
from app.agent.tools import SupportToolContext
from app.schema.ticket_edit import EDIT_LABELS, TicketChanges
from app.schema.ticket_query import TicketQueryInput
from app.services.ticket_edit_service import TicketEditService
from app.services.ticket_query_service import TicketQueryService

STATUS_LABELS = {
    "open": "待处理",
    "in_progress": "处理中",
    "waiting_customer": "等待客户",
    "resolved": "已解决",
    "closed": "已关闭",
}


async def prepare_ticket_edit_node(
    state: SupportAgentState, runtime: Runtime[SupportToolContext]
) -> dict[str, Any]:
    memory = state["edit_memory"].model_copy(deep=True)

    def reply(text: str) -> dict[str, Any]:
        return {
            "edit_memory": memory,
            "final_reply": text,
            "messages": [AIMessage(content=text)],
        }

    if memory.stage == "select":
        if memory.reference.isdecimal():
            return reply("该序号不在已展示的列表中，请回复有效序号或完整工单编号。")
        async with asyncio.timeout(30):
            page = await TicketQueryService(runtime.context.session).search(
                runtime.context.conversation_id,
                TicketQueryInput(
                    ticket_code=memory.reference
                    if memory.reference.startswith("TK-")
                    else "",
                    keyword=memory.reference
                    if not memory.reference.startswith("TK-")
                    else "",
                ),
            )
        memory.candidates = [item.code for item in page.items]
        if not page.items:
            memory.reference = ""
            return reply(
                "未找到您在当前企业的匹配工单，请提供正确的编号或问题关键词。本次未修改。"
            )
        options = "\n".join(
            f"{i}. {item.code}｜{item.title}｜{STATUS_LABELS.get(item.status, item.status)}"
            for i, item in enumerate(page.items, 1)
        )
        # 即使只匹配一张，也不能把查询结果当成用户选择。
        return reply(
            "请选择要跟进的工单，回复序号或完整编号：\n"
            + options
            + (
                "\n仅展示最近五条匹配工单，可提供编号缩小范围。"
                if page.has_more
                else ""
            )
        )
    async with asyncio.timeout(30):
        ticket = await TicketEditService(runtime.context.session).snapshot(
            runtime.context.conversation_id, memory.reference
        )
    if ticket is None:
        memory.stage, memory.candidates, memory.version = "select", [], None
        return reply("工单已不可访问，请重新提供工单编号。本次未修改。")
    if ticket.status == "closed":
        memory.stage, memory.confirmed = "done", False
        return reply(f"工单 {ticket.code} 已关闭，只能查看，不能修改。")
    # 每轮展示来自真实数据；即使预览后只改了状态，也要求客户核对最新版本。
    stale = memory.version is not None and memory.version != ticket.version
    if memory.stage == "confirm" and memory.confirmed and not stale:
        return {
            "edit_memory": memory,
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "update_support_ticket",
                            "args": {
                                "ticket_code": ticket.code,
                                "expected_version": ticket.version,
                                "changes": memory.changes.patch(),
                            },
                            "id": str(uuid4()),
                        }
                    ],
                )
            ],
        }
    memory.version, memory.confirmed = ticket.version, False
    snapshot = "\n".join(
        f"{index}、{label}：{getattr(ticket, key) or '未填写'}"
        for index, (key, label) in enumerate(EDIT_LABELS.items(), 1)
    )
    # 只读订单独立成区，不编号，避免用户误以为可以通过修改描述更换订单。
    order_info = (
        f"\n关联订单（只读）：\n商品：{ticket.order.product_name}\n订单号：{ticket.order.code}\n"
        if ticket.order else ""
    )
    text = f"已选择工单 {ticket.code}，状态：{STATUS_LABELS.get(ticket.status, ticket.status)}。{order_info}\n当前可修改信息：\n{snapshot}\n问题描述只需填写故障或遇到的问题，不需要重复订单号和商品。\n状态、关联订单、负责人和系统优先级不能在此修改。"
    patch = {
        key: value
        for key, value in memory.changes.patch().items()
        if getattr(ticket, key) != value
    }
    memory.changes = TicketChanges.model_validate(patch)
    if not patch:
        memory.stage = "edit"
        return reply(text + "\n请告诉我要修改哪些内容，未提及字段保持不变。")
    memory.stage = "confirm"
    preview = "\n".join(
        f"{EDIT_LABELS[key]}：{getattr(ticket, key) or '未填写'} → {value or '未填写'}"
        for key, value in patch.items()
    )
    return reply(
        ("工单已被更新，请核对最新内容后重新确认。\n" if stale else "")
        + text
        + "\n拟修改内容：\n"
        + preview
        + "\n回复“确认修改”后提交，也可以继续更正或回复“取消修改”。"
    )


def finalize_ticket_edit_node(state: SupportAgentState) -> dict[str, Any]:
    result = state.get("edit_result")
    if result is None:
        raise RuntimeError("缺少修改工单结果")
    return {
        "final_reply": result.message,
        "messages": [AIMessage(content=result.message)],
    }
