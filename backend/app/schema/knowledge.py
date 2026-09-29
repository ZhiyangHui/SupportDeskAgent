"""知识库只接收文本，禁止企业身份和向量数据由客户端指定。"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=60000)


class KnowledgeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    published: bool
    chunk_count: int
    created_at: datetime
    source_kind: Literal["document", "ticket_case"] = "document"


class KnowledgeSearch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=500)


class KnowledgeChunkDetail(BaseModel):
    """只返回可阅读的片段，不向浏览器传输向量。"""
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    position: int
    content: str
    heading_path: str = ""
    version: int = 0


class DraftChunk(BaseModel):
    """可编辑草稿有独立边界，不接收向量或企业身份。"""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    heading_path: str = Field(min_length=1, max_length=1500)
    content: str = Field(min_length=1, max_length=2000)


class DraftRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)


class KnowledgePublish(DraftRevision):
    # 只在员工显式审核时为 true；不能因为“有片段”就当作已经完成隐私核查。
    confirm_case_review: bool = False


class TicketExperienceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    ticket_code: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=160)
    symptom: str = Field(min_length=1, max_length=1500)
    cause: str = Field(min_length=1, max_length=1500)
    solution: str = Field(min_length=1, max_length=1500)
    applicability: str = Field(min_length=1, max_length=1500)


class ExperienceTicketOption(BaseModel):
    code: str
    title: str
    status: str


class ExperienceTicketSource(ExperienceTicketOption):
    """员工专用的脱敏素材，不是已审核的公开知识。"""
    description: str
    desired_resolution: str
    impact_note: str


class DraftUpdate(DraftRevision):
    chunks: list[DraftChunk] = Field(min_length=1, max_length=300)


class KnowledgeDetail(KnowledgeSummary):
    content: str
    chunks: list[KnowledgeChunkDetail]
    draft_chunks: list[DraftChunk] = Field(default_factory=list)
    draft_revision: int = 0
    published_revision: int = 0
    draft_warnings: list[str] = Field(default_factory=list)
    source_ticket_id: UUID | None = None
    reviewed_at: datetime | None = None


class KnowledgeHit(BaseModel):
    document_id: UUID
    chunk_id: UUID
    title: str
    position: int
    content: str
    score: float
    source_kind: Literal["document", "ticket_case"] = "document"


class KnowledgeAnswer(BaseModel):
    """来源必须由程序核对，模型只能选择真实检索片段的序号。"""
    answer: str = Field(min_length=1, max_length=4000)
    source_numbers: list[int] = Field(default_factory=list, max_length=5)
