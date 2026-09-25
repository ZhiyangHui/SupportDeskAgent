"""确定性的售后节点：模型负责理解，程序负责候选顺序、选择和写入门槛。"""

from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage

from app.agent.state import SupportAgentState


def order_workflow_node(state: SupportAgentState) -> dict[str, Any]:
    """每轮先读取实时订单；仅选择唯一且诉求齐全时交由 ToolNode 写入。"""

    memory = state["order_memory"].model_copy(deep=True)

    def reply(text: str) -> dict[str, Any]:
        return {
            "order_memory": memory,
            "final_reply": text,
            "messages": [AIMessage(content=text)],
        }

    def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "order_memory": memory,
            "should_create_ticket": memory.stage == "ready",
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"name": name, "args": args, "id": str(uuid4())}],
                )
            ],
        }

    def choices() -> str:
        # 该列表就是下一轮数字映射的事实来源，不能再让 LLM 调整顺序或删减。
        return "\n".join(
            f"{index}. {item.product_name}（{item.code}）"
            for index, item in enumerate(memory.candidates, 1)
        )

    if not state.get("order_rounds"):
        if memory.reference.isdecimal() and memory.selected is None:
            return reply(
                "该序号不在当前列表中，请选择有效序号或提供订单号：\n" + choices()
            )
        reference = memory.selected.code if memory.selected else memory.reference
        return call(
            "query_my_orders",
            {
                "order_code": reference if reference.startswith("MO-") else "",
                "keyword": reference
                if reference and not reference.startswith("MO-")
                else "",
            },
        )

    memory.candidates = state.get("order_candidates", [])
    if len(memory.candidates) != 1:
        memory.selected = None
        memory.stage = "select_order"
        memory.reference = ""
        if not memory.candidates:
            return reply(
                "当前企业未找到匹配订单，请核对订单号或商品名。本次未创建工单。"
            )
        return reply(
            "找到多笔订单，请告诉我要处理哪一笔：\n"
            + choices()
            + (
                "\n可回复序号；售后诉求已保留。"
                if memory.issue
                else "\n可回复序号，并说明售后诉求（如维修、退款）。"
            )
        )

    memory.selected = memory.candidates[0]
    memory.reference = memory.selected.code
    if len(memory.issue.strip()) < 2:
        memory.stage = "collect_issue"
        return reply(
            f"已确认：{memory.selected.product_name}（{memory.selected.code}）。请说明售后诉求，例如维修、退款或换货。"
        )
    memory.stage = "ready"
    # UUID 只取本轮受权限约束的查询结果，不接受模型或历史快照传入写入目标。
    return call(
        "create_order_ticket",
        {"order_id": state["available_order_ids"][0], "issue": memory.issue},
    )
