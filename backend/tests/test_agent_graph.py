from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.graph import DecisionModel, ToolCallingModel, build_support_graph
from app.agent.schemas import (
    AgentDecision,
    SupportIntent,
    TicketCategory,
    TicketPriority,
)
from app.agent.tools import SupportToolContext
from app.db.models import Ticket, TicketPriorityValue, TicketSource, TicketStatus


class StubDecisionModel:
    """使用固定结构化结果测试 Graph 路由，不依赖网络和真实模型费用。"""

    def __init__(self, decision: AgentDecision) -> None:
        self.decision = decision

    async def ainvoke(self, input):
        return self.decision


class StubTicketCallingModel:
    """模拟模型生成标准业务 Tool Call，工具本身仍由真实 ToolNode 执行。"""

    async def ainvoke(self, input):
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "create_support_ticket",
                    "args": {
                        "title": "企业账号无法登录",
                        "description": "客户登录企业控制台时提示账号被锁定，希望客服协助核验。",
                        "category": "account",
                        "priority": "high",
                    },
                    "id": "tool-call-test-001",
                    "type": "tool_call",
                }
            ],
        )


@pytest.mark.asyncio
async def test_general_question_uses_automatic_reply() -> None:
    """普通咨询应该直接回复，并保留模型给出的结构化判断。"""

    decision = AgentDecision(
        intent=SupportIntent.GENERAL,
        priority=TicketPriority.LOW,
        requires_human=False,
        should_create_ticket=False,
        needs_ticket_details=False,
        reason="属于普通产品咨询",
        reply="您好，可以在控制台的帮助中心查看操作说明。",
    )
    graph = build_support_graph(cast(DecisionModel, StubDecisionModel(decision)))

    result = await graph.ainvoke({"messages": [HumanMessage(content="在哪里看帮助文档？")]})

    assert result["final_reply"] == decision.reply
    assert result["requires_human"] is False


@pytest.mark.asyncio
async def test_risky_request_uses_human_handoff() -> None:
    """高风险请求必须进入人工分支，最终回复应明确告知已经转交。"""

    decision = AgentDecision(
        intent=SupportIntent.ACCOUNT,
        priority=TicketPriority.HIGH,
        requires_human=True,
        should_create_ticket=False,
        needs_ticket_details=False,
        reason="涉及企业账号安全",
        reply="我需要进一步核验您的账号状态。",
    )
    graph = build_support_graph(cast(DecisionModel, StubDecisionModel(decision)))

    result = await graph.ainvoke({"messages": [HumanMessage(content="企业账号被异常锁定了")]})

    assert result["requires_human"] is True
    assert "转交人工客服" in result["final_reply"]


@pytest.mark.asyncio
async def test_explicit_ticket_request_calls_real_ticket_tool(monkeypatch) -> None:
    """明确建单请求必须经过 AIMessage Tool Call 和 ToolNode，不能由 Service 绕过。"""

    decision = AgentDecision(
        intent=SupportIntent.TICKET,
        priority=TicketPriority.HIGH,
        requires_human=True,
        should_create_ticket=True,
        needs_ticket_details=False,
        ticket_title="企业账号无法登录",
        ticket_description="客户登录企业控制台时提示账号被锁定，希望客服协助核验。",
        ticket_category=TicketCategory.ACCOUNT,
        reason="用户明确要求为登录故障创建工单",
        reply="已整理您的问题，准备创建工单。",
    )
    created_ticket = Ticket(
        id=uuid4(),
        code="TK-TEST-TOOL-001",
        title="企业账号无法登录",
        description="客户登录企业控制台时提示账号被锁定，希望客服协助核验。",
        category="account",
        status=TicketStatus.OPEN,
        priority=TicketPriorityValue.HIGH,
        source=TicketSource.AGENT,
        version=1,
    )
    create_ticket_mock = AsyncMock(return_value=created_ticket)
    monkeypatch.setattr("app.agent.tools.TicketService.create_ticket", create_ticket_mock)
    graph = build_support_graph(
        cast(DecisionModel, StubDecisionModel(decision)),
        cast(ToolCallingModel, StubTicketCallingModel()),
    )

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="请帮我创建工单，企业账号登录时提示被锁定")]},
        context=SupportToolContext(session=AsyncMock(), conversation_id=uuid4()),
    )

    assert result["should_create_ticket"] is True
    assert result["created_ticket_code"] == "TK-TEST-TOOL-001"
    assert "TK-TEST-TOOL-001" in result["final_reply"]
    create_ticket_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_incomplete_ticket_request_asks_for_all_details_once() -> None:
    """只有建单意愿但没有问题内容时，应进入专用收集节点而不是普通回复。"""

    decision = AgentDecision(
        intent=SupportIntent.TICKET,
        priority=TicketPriority.MEDIUM,
        requires_human=False,
        should_create_ticket=False,
        needs_ticket_details=True,
        reason="用户要求建单，但没有说明具体问题",
        reply="请补充问题详情。",
    )
    graph = build_support_graph(cast(DecisionModel, StubDecisionModel(decision)))

    result = await graph.ainvoke({"messages": [HumanMessage(content="帮我创建一个工单")]})

    assert result["needs_ticket_details"] is True
    assert "具体问题或报错现象" in result["final_reply"]
    assert "相关账号、订单号" in result["final_reply"]
