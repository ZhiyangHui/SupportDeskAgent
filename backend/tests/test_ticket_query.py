"""查询工具循环的确定性测试，不调用付费模型，仍执行真实 ToolNode。"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.graph import build_support_graph
from app.agent.schemas import AgentDecision
from app.agent.tools import SupportToolContext, query_support_tickets
from app.schema.ticket_query import TicketQueryResult
from tests.test_agent_graph import StubDecisionLLM


class StubTicketQueryLLM:
    """先生成工具调用，再读取工具结果；可切换为持续查询以测试上限。"""

    def __init__(self, *, repeat=False, name="query_support_tickets", args=None):
        self.repeat = repeat
        self.name = name
        self.args = args or {}
        self.results = []

    async def ainvoke(self, messages):
        if isinstance(messages[-1], ToolMessage):
            self.results.append(messages[-1].content)
            if not self.repeat:
                return AIMessage(content="已核对工单，请根据查询结果选择编号。")
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": self.name,
                    "args": self.args,
                    "id": str(uuid4()),
                    "type": "tool_call",
                }
            ],
        )


def query_graph(llm):
    """查询意图单独构造，避免旧建单测试的固定响应干扰路由。"""

    return build_support_graph(
        StubDecisionLLM(
            AgentDecision(
                intent="ticket",
                priority="low",
                requires_human=False,
                should_create_ticket=False,
                needs_ticket_details=False,
                should_query_ticket=True,
                reason="客户查询进度",
                reply="准备查询",
            )
        ),
        ticket_query_llm=llm,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 5])
async def test_query_returns_safe_results_to_model(monkeypatch, count):
    result = TicketQueryResult.model_validate(
        {
            "items": [
                {
                    "code": f"TK-{i}",
                    "title": "登录失败",
                    "status": "open",
                    "updated_at": "2026-09-14T00:00:00Z",
                }
                for i in range(count)
            ]
        }
    )
    search = AsyncMock(return_value=result)
    monkeypatch.setattr("app.agent.tools.TicketQueryService.search", search)
    llm = StubTicketQueryLLM()
    state = await query_graph(llm).ainvoke(
        {"messages": [HumanMessage(content="我的工单处理到哪了")]},
        context=SupportToolContext(AsyncMock(), uuid4()),
    )
    assert state["executed_tool"] == "query_support_tickets"
    assert state["query_rounds"] == 1
    assert llm.results == [result.model_dump_json()]
    assert not state.get("created_ticket_id")
    search.assert_awaited_once()


@pytest.mark.asyncio
async def test_query_loop_is_bounded(monkeypatch):
    search = AsyncMock(return_value=TicketQueryResult(items=[]))
    monkeypatch.setattr("app.agent.tools.TicketQueryService.search", search)
    state = await query_graph(StubTicketQueryLLM(repeat=True)).ainvoke(
        {"messages": [HumanMessage(content="查询工单")]},
        context=SupportToolContext(AsyncMock(), uuid4()),
    )
    assert search.await_count == 3
    assert "三次" in state["final_reply"]


@pytest.mark.asyncio
async def test_query_rejects_write_tool():
    with pytest.raises(RuntimeError, match="只读"):
        await query_graph(StubTicketQueryLLM(name="create_support_ticket")).ainvoke(
            {"messages": [HumanMessage(content="查询工单")]},
        )


@pytest.mark.asyncio
async def test_query_database_failure_is_not_empty_result(monkeypatch):
    monkeypatch.setattr(
        "app.agent.tools.TicketQueryService.search",
        AsyncMock(side_effect=RuntimeError("数据库不可用")),
    )
    with pytest.raises(RuntimeError, match="数据库不可用"):
        await query_graph(StubTicketQueryLLM()).ainvoke(
            {"messages": [HumanMessage(content="查询工单")]},
            context=SupportToolContext(AsyncMock(), uuid4()),
        )


def test_query_tool_hides_runtime_identity():
    assert set(query_support_tickets.tool_call_schema.model_fields) == {
        "ticket_code",
        "keyword",
    }


@pytest.mark.asyncio
async def test_query_cannot_claim_result_without_tool():
    """模型直接声称查到结果时拒绝采信，避免生成貌似真实的工单状态。"""

    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content="您的工单已解决")
    with pytest.raises(RuntimeError, match="未调用工单查询工具"):
        await query_graph(llm).ainvoke(
            {"messages": [HumanMessage(content="查询进度")]}
        )


def test_query_and_create_intents_are_exclusive():
    """错误结构化决策必须在路由之前被拦截，避免查询触发建单。"""

    with pytest.raises(ValueError, match="查询工单不能同时"):
        AgentDecision(
            intent="ticket",
            priority="low",
            requires_human=False,
            should_create_ticket=True,
            needs_ticket_details=False,
            should_query_ticket=True,
            reason="冲突",
            reply="冲突",
        )
