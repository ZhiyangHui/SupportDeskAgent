"""RAG 工具与来源边界：使用模型替身，不调用任何付费 API。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.agent.graph import build_support_graph
from app.agent.schemas import AgentDecision
from app.agent.tools import SupportToolContext
from app.core.config import get_settings
from app.schema.knowledge import KnowledgeAnswer, KnowledgeHit
from app.services.knowledge_service import (
    KnowledgeService,
    KnowledgeUnavailableError,
    embedding_client,
    embedding_profile,
    validate_vectors,
)


def test_structural_chunks_keep_topics_separate():
    """商品和主题都进入路径，不会为了填满长度把不同业务规则混在一起。"""
    from app.services.knowledge_chunking import build_draft
    chunks, _ = build_draft("政策", "# 政策\n## 无线键盘\n### 退货\n七天退货。\n### 维修\n保修十二个月。\n## 机械设备\n### 维修\n保修二十四个月。")
    assert len(chunks) == 3
    assert chunks[0].heading_path == "政策 / 无线键盘 / 退货"
    assert chunks[1].content == "保修十二个月。"
    assert chunks[2].heading_path == "政策 / 机械设备 / 维修"


def test_plain_headings_and_long_fallback():
    from app.services.knowledge_chunking import build_draft
    chunks, _ = build_draft("政策", "一、键盘\n退货\n七天。\n维修\n一年。\n二、设备\n维修\n两年。")
    assert len(chunks) == 3
    assert "二、设备" in chunks[-1].heading_path
    chunks, warnings = build_draft("普通文本", "维修规则" * 300)
    assert len(chunks) > 1 and all(len(chunk.content) <= 500 for chunk in chunks)
    assert warnings


@pytest.mark.asyncio
@pytest.mark.parametrize("old_chunks", [["旧的大块"], ["新的片段"]])
async def test_publish_rebuilds_changed_chunks(monkeypatch, old_chunks):
    """模型未变也要重建旧分块；片段和模型都一致时才复用，避免重复收费。"""

    monkeypatch.setattr("app.services.knowledge_service.validate_vectors", lambda *_: None)
    client = AsyncMock()
    client.aembed_documents.return_value = [[1.0]]
    monkeypatch.setattr("app.services.knowledge_service.embedding_client", lambda: client)
    session = AsyncMock()
    session.add_all = Mock()
    session.scalars.return_value = [SimpleNamespace(heading_path="政策", content=text) for text in old_chunks]
    service = KnowledgeService(session, uuid4())
    row = SimpleNamespace(content="原文", chunk_count=1, embedding_profile=embedding_profile(), published=False,
        draft_revision=1, draft_chunks=[{"heading_path": "政策", "content": "新的片段"}])
    service.owned = AsyncMock(return_value=row)
    await service.publish(uuid4(), 1)
    if old_chunks == ["旧的大块"]:
        client.aembed_documents.assert_awaited_once_with(["所属章节：政策\n\n新的片段"])
        session.execute.assert_awaited_once()
    else:
        client.aembed_documents.assert_not_awaited()
    assert row.published


@pytest.mark.parametrize("numbers", [[1], [9], []])
@pytest.mark.asyncio
async def test_rag_calls_read_only_tool_and_validates_sources(monkeypatch, numbers):
    company, customer, conversation = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr("app.agent.tools.ConversationRepository.get_conversation", AsyncMock(return_value=SimpleNamespace(company_id=company, customer_id=customer)))
    hit = KnowledgeHit(document_id=uuid4(), chunk_id=uuid4(), title="企业售后政策", position=1, content="签收七天内，未使用可申请退货。", score=0.9)
    search = AsyncMock(return_value=[hit])
    monkeypatch.setattr("app.services.knowledge_service.KnowledgeService.search", search)
    writer = AsyncMock(side_effect=AssertionError("知识分支不得建单"))
    monkeypatch.setattr("app.agent.tools.TicketService.create_ticket", writer)
    decision = AsyncMock()
    decision.ainvoke.return_value = AgentDecision(intent="general", priority="low", requires_human=False,
        should_create_ticket=False, needs_ticket_details=False, should_search_knowledge=True,
        knowledge_query="退货政策是什么", reason="查询企业政策", reply="正在检索")
    answer = AsyncMock()
    answer.ainvoke.return_value = KnowledgeAnswer(answer="未使用商品可在签收七天内申请退货。", source_numbers=numbers)
    graph = build_support_graph(decision, knowledge_llm=answer)
    result = await graph.ainvoke({"messages": [HumanMessage(content="退货政策是什么")]},
        context=SupportToolContext(AsyncMock(), conversation, customer, company))
    assert result["executed_tool"] == "search_company_knowledge"
    assert any(isinstance(message, ToolMessage) for message in result["messages"])
    search.assert_awaited_once_with("退货政策是什么")
    writer.assert_not_awaited()
    if numbers == [1]:
        assert "来源：《企业售后政策》（片段 1）" in result["final_reply"]
        assert "摘录：" not in result["final_reply"]
    else:
        assert "不足以确认" in result["final_reply"]
        assert "来源：" not in result["final_reply"]


def test_embedding_config_and_invalid_vectors(monkeypatch):
    settings = get_settings().model_copy(update={"knowledge_enabled": False, "embedding_dimensions": 3})
    monkeypatch.setattr("app.services.knowledge_service.get_settings", lambda: settings)
    with pytest.raises(KnowledgeUnavailableError):
        embedding_client()
    for vectors in ([], [[0, 0, 0]], [[1, 2]], [[float("nan"), 1, 2]]):
        with pytest.raises(KnowledgeUnavailableError):
            validate_vectors(vectors, 1)
    validate_vectors([[1, 0, 0]], 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", ["", "向量服务未配置"])
async def test_no_evidence_does_not_call_answer_model(error):
    from app.agent.workflows.knowledge_workflow import knowledge_answer_node
    model = AsyncMock()
    result = await knowledge_answer_node(model)({"knowledge_hits": [], "knowledge_error": error})
    model.ainvoke.assert_not_awaited()
    assert "准确答复" in result["final_reply"]


@pytest.mark.asyncio
async def test_sources_are_compact_and_grouped_by_document():
    """同一文档只展示一次，保留真实片段位置，不把正文摘录重复放入回答。"""
    from app.agent.workflows.knowledge_workflow import knowledge_answer_node
    model = AsyncMock()
    model.ainvoke.return_value = KnowledgeAnswer(answer="不适用，这项模拟补偿只针对 X999。", source_numbers=[1, 2, 1])
    document_id = str(uuid4())
    result = await knowledge_answer_node(model)({"knowledge_query": "普通键盘适用吗？", "knowledge_hits": [
        {"document_id": document_id, "title": "模拟规则", "position": position, "content": "用于核对的完整规则"}
        for position in [2, 3]
    ]})
    assert result["final_reply"] == "不适用，这项模拟补偿只针对 X999。\n\n来源：《模拟规则》（片段 2、3）"
