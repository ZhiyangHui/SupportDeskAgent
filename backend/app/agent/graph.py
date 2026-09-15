import asyncio
import json
from time import monotonic
from typing import Any, Literal, Protocol

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import ValidationError

from app.agent.prompts import QUERY_PROMPT, SYSTEM_PROMPT
from app.agent.schemas import AgentDecision
from app.agent.state import SupportAgentState
from app.agent.tools import (
    SupportToolContext,
    create_support_ticket,
    query_support_tickets,
)
from app.schema.ticket_query import TicketQueryInput
from app.services.agent_errors import ModelOutputError


class DecisionModel(Protocol):
    """约束结构化模型的最小接口，便于在测试中替换为确定性实现。"""

    async def ainvoke(self, input: list[BaseMessage]) -> AgentDecision: ...


class ToolCallingModel(Protocol):
    """工具选择模型必须返回包含 Tool Call 的 AIMessage。"""

    async def ainvoke(self, input: list[BaseMessage]) -> AIMessage: ...


def build_support_graph(
    decision_model: DecisionModel,
    ticket_calling_model: ToolCallingModel | None = None,
    query_calling_model: ToolCallingModel | None = None,
):
    """构建客服处理图，模型负责判断，Graph 负责可审计的流程分支。"""

    async def analyze_request(state: SupportAgentState) -> dict[str, Any]:
        """读取完整会话并生成结构化判断，不在此节点直接产生最终消息。"""

        # System Prompt 每次都放在会话首部，防止用户消息改变 Agent 的基本安全规则。
        decision_messages: list[BaseMessage] = [
            SystemMessage(content=SYSTEM_PROMPT),
            *state["messages"],
        ]
        for attempt in range(2):
            try:
                decision = await decision_model.ainvoke(decision_messages)
                break
            except (ValidationError, OutputParserException) as exc:
                # 仅纠正结构错误，不把供应商错误原文放进提示词，也不重试任何工具副作用。
                if attempt:
                    raise ModelOutputError("结构化判断纠正后仍不合法") from exc
                # 只提供字段名和错误类型，不回传异常里的原始输入、客户内容或供应商响应。
                # 完整 Schema 来自代码，包含枚举和长度限制，避免模型不知道该改哪个值。
                issues = []
                if isinstance(exc, ValidationError):
                    for issue in exc.errors(
                        include_input=False, include_url=False, include_context=False
                    ):
                        field = issue["loc"][0] if issue["loc"] else None
                        issues.append(
                            {
                                "field": field
                                if field in AgentDecision.model_fields
                                else "整体结构",
                                "type": issue["type"],
                            }
                        )
                correction = (
                    "\n上次输出不符合协议。错误字段与类型："
                    + json.dumps(issues, ensure_ascii=False)
                    + "。请按以下 Schema 的合法枚举、必填项和长度限制重新输出；建单、查询、等待补充不能冲突：\n"
                    + json.dumps(AgentDecision.model_json_schema(), ensure_ascii=False)
                )
                decision_messages = [
                    SystemMessage(content=SYSTEM_PROMPT + correction),
                    *state["messages"],
                ]
        return {
            "intent": decision.intent,
            "priority": decision.priority,
            "requires_human": decision.requires_human,
            "should_create_ticket": decision.should_create_ticket,
            "should_query_ticket": decision.should_query_ticket,
            "query_rounds": 0,
            # 限制整个查询循环的时间，不能只限制每个模型请求而无限累计等待。
            "query_deadline": monotonic() + 90,
            "needs_ticket_details": decision.needs_ticket_details,
            "ticket_title": decision.ticket_title,
            "ticket_description": decision.ticket_description,
            "ticket_category": decision.ticket_category,
            "decision_reason": decision.reason,
            "reply_draft": decision.reply,
        }

    def choose_route(
        state: SupportAgentState,
    ) -> Literal[
        "request_ticket_tool",
        "collect_ticket_details",
        "human_handoff",
        "automatic_reply",
        "query_model",
    ]:
        """建单意图优先进入工单分支，其余高风险请求再转人工。"""

        if state["should_query_ticket"]:
            return "query_model"
        if state["should_create_ticket"]:
            return "request_ticket_tool"
        if state["needs_ticket_details"]:
            return "collect_ticket_details"
        return "human_handoff" if state["requires_human"] else "automatic_reply"

    def collect_ticket_details(state: SupportAgentState) -> dict[str, Any]:
        """采用结合历史生成的追问；固定清单会覆盖模型判断，造成多轮重复询问。"""

        # 此分支只追加客户可见消息，不调用写入工具；建单仍须后续通过结构化判断。
        reply = state["reply_draft"]
        return {"final_reply": reply, "messages": [AIMessage(content=reply)]}

    async def request_ticket_tool(state: SupportAgentState) -> dict[str, Any]:
        """让绑定了业务 Tool 的模型生成真实 Tool Call，而不是由 Service 模拟工具执行。"""

        if ticket_calling_model is None:
            raise RuntimeError("工单 Tool Calling 模型未配置")
        tool_arguments = {
            "title": state["ticket_title"],
            "description": state["ticket_description"],
            "category": state["ticket_category"].value,
            "priority": state["priority"].value,
        }
        instruction = (
            "你必须调用 create_support_ticket 工具，并严格使用下列已经校验的参数，"
            "不得改写、补充或省略字段：\n"
            f"{json.dumps(tool_arguments, ensure_ascii=False)}"
        )
        for attempt in range(2):
            tool_call_message = await ticket_calling_model.ainvoke(
                [SystemMessage(content=instruction)]
            )
            calls = tool_call_message.tool_calls
            # 名称、数量和参数都由服务端核对；仅提示“严格使用”不足以防止模型改写。
            if (
                len(calls) == 1
                and calls[0]["name"] == "create_support_ticket"
                and calls[0]["args"] == tool_arguments
            ):
                return {"messages": [tool_call_message]}
            if not attempt:
                instruction = (
                    "上次调用不符合协议。只生成一次指定工具调用，参数必须与下列 JSON 完全一致。\n"
                    + instruction
                )
        raise ModelOutputError("建单工具调用纠正后仍不合法，未执行建单")

    def finalize_ticket(state: SupportAgentState) -> dict[str, Any]:
        """Tool 成功后使用回写的真实编号构造回复，禁止在执行前承诺建单成功。"""

        ticket_code = state.get("created_ticket_code")
        if not ticket_code:
            raise RuntimeError("工单 Tool 未返回工单编号")
        priority_label = {
            "low": "低",
            "medium": "中",
            "high": "高",
            "urgent": "紧急",
        }[state["priority"].value]
        reply = (
            f"已为您创建工单 {ticket_code}，当前优先级为{priority_label}。"
            "您可以在工单中心查看后续处理进度。"
        )
        return {"final_reply": reply, "messages": [AIMessage(content=reply)]}

    def automatic_reply(state: SupportAgentState) -> dict[str, Any]:
        """普通咨询直接采用经过结构化约束的回复草稿。"""

        reply = state["reply_draft"]
        return {"final_reply": reply, "messages": [AIMessage(content=reply)]}

    def human_handoff(state: SupportAgentState) -> dict[str, Any]:
        """当前尚无实时人工接管，不把路由判断冒充为已完成转交。"""

        # 使用确定性说明，避免模型草稿承诺已经接通人工或执行了退款等操作。
        reply = "这个问题需要人工进一步核验。目前尚未开放实时转交人工客服，您可以描述问题并要求创建工单，由客服在企业工作台跟进。"
        return {"final_reply": reply, "messages": [AIMessage(content=reply)]}

    async def query_model(state: SupportAgentState) -> dict[str, Any]:
        """只读工具循环：首次必须查询，此后允许回答或再次缩小条件，最多三次。"""

        if query_calling_model is None:
            raise RuntimeError("工单查询模型未配置")
        instruction = QUERY_PROMPT
        remaining = state["query_deadline"] - monotonic()
        if remaining <= 0:
            raise TimeoutError("工单查询超过总时间预算")
        async with asyncio.timeout(remaining):
            for attempt in range(2):
                message = await query_calling_model.ainvoke(
                    [SystemMessage(content=instruction), *state["messages"]]
                )
                try:
                    if message.tool_calls:
                        # 写工具或并行调用是越界而非普通格式错误，直接拒绝，不给予执行机会。
                        if (
                            len(message.tool_calls) != 1
                            or message.tool_calls[0]["name"] != "query_support_tickets"
                        ):
                            raise ModelOutputError("查询分支只允许单次调用只读查询工具")
                        TicketQueryInput.model_validate(message.tool_calls[0]["args"])
                    elif not state.get("query_rounds"):
                        if attempt:
                            raise ModelOutputError(
                                "模型未调用工单查询工具，不能直接报告查询结果"
                            )
                        instruction = (
                            QUERY_PROMPT
                            + "\n上次缺少工具调用，本轮尚未查询，请先生成 query_support_tickets 调用。"
                        )
                        continue
                    elif (
                        not isinstance(message.content, str)
                        or not message.content.strip()
                    ):
                        if attempt:
                            raise ModelOutputError("查询模型未返回有效回复")
                        instruction = (
                            QUERY_PROMPT
                            + "\n上次回复为空，请根据已有工具结果给出非空中文回复。"
                        )
                        continue
                    break
                except ValidationError as exc:
                    if attempt:
                        raise ModelOutputError("查询参数纠正后仍不合法") from exc
                    instruction = (
                        QUERY_PROMPT
                        + "\n上次参数无效：只能包含 ticket_code 和 keyword 两个字符串字段，各最多 100 字。"
                    )
        if message.tool_calls:
            # 同一个 AsyncSession 不能并发执行 SQL，也不允许借查询入口调用写入工具。
            if (
                len(message.tool_calls) != 1
                or message.tool_calls[0]["name"] != "query_support_tickets"
            ):
                raise ModelOutputError("查询分支只允许单次调用只读查询工具")
            if state.get("query_rounds", 0) >= 3:
                reply = "本轮已完成三次查询。请提供准确的工单编号或更具体的问题关键词，以便继续核对。"
                return {"final_reply": reply, "messages": [AIMessage(content=reply)]}
            return {"messages": [message]}
        if not state.get("query_rounds"):
            raise ModelOutputError("模型未调用工单查询工具，不能直接报告查询结果")
        if not isinstance(message.content, str) or not message.content.strip():
            raise ModelOutputError("查询模型未返回有效回复")
        return {"messages": [message], "final_reply": message.content}

    def after_query_model(
        state: SupportAgentState,
    ) -> Literal["query_tools", "__end__"]:
        """只有校验通过的工具请求才交给 ToolNode，普通回答结束本轮。"""

        last = state["messages"][-1]
        return (
            "query_tools"
            if isinstance(last, AIMessage) and last.tool_calls
            else "__end__"
        )

    graph = StateGraph(SupportAgentState, context_schema=SupportToolContext)
    graph.add_node("query_model", query_model)
    graph.add_node(
        "query_tools", ToolNode([query_support_tickets], handle_tool_errors=False)
    )
    graph.add_conditional_edges("query_model", after_query_model)
    graph.add_edge("query_tools", "query_model")
    graph.add_node("analyze_request", analyze_request)
    graph.add_node("automatic_reply", automatic_reply)
    graph.add_node("human_handoff", human_handoff)
    graph.add_node("collect_ticket_details", collect_ticket_details)
    graph.add_node("request_ticket_tool", request_ticket_tool)
    # Tool 异常向上传播，由 API 记录请求 ID 并返回 502；不能伪装成建单成功。
    graph.add_node(
        "ticket_tools", ToolNode([create_support_ticket], handle_tool_errors=False)
    )
    graph.add_node("finalize_ticket", finalize_ticket)

    # 节点名称保持业务语义，后续接入 LangSmith 后可以直接读懂完整调用链。
    graph.add_edge(START, "analyze_request")
    graph.add_conditional_edges("analyze_request", choose_route)
    graph.add_edge("automatic_reply", END)
    graph.add_edge("human_handoff", END)
    graph.add_edge("collect_ticket_details", END)
    graph.add_edge("request_ticket_tool", "ticket_tools")
    graph.add_edge("ticket_tools", "finalize_ticket")
    graph.add_edge("finalize_ticket", END)
    return graph.compile()
