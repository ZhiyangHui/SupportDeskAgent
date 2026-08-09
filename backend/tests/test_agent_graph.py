from typing import cast

import pytest
from langchain_core.messages import HumanMessage

from app.agent.graph import DecisionModel, build_support_graph
from app.agent.schemas import AgentDecision, SupportIntent, TicketPriority


class StubDecisionModel:
    """使用固定结构化结果测试 Graph 路由，不依赖网络和真实模型费用。"""

    def __init__(self, decision: AgentDecision) -> None:
        self.decision = decision

    async def ainvoke(self, input):
        return self.decision


@pytest.mark.asyncio
async def test_general_question_uses_automatic_reply() -> None:
    """普通咨询应该直接回复，并保留模型给出的结构化判断。"""

    decision = AgentDecision(
        intent=SupportIntent.GENERAL,
        priority=TicketPriority.LOW,
        requires_human=False,
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
        reason="涉及企业账号安全",
        reply="我需要进一步核验您的账号状态。",
    )
    graph = build_support_graph(cast(DecisionModel, StubDecisionModel(decision)))

    result = await graph.ainvoke({"messages": [HumanMessage(content="企业账号被异常锁定了")]})

    assert result["requires_human"] is True
    assert "转交人工客服" in result["final_reply"]

