"""企业知识库：文档与切片独立保存；只发布索引完成且明确允许客户阅读的资料。"""
from datetime import datetime
from uuid import UUID, uuid4

# 官方包暂未声明完整类型信息，只对这个外部导入放宽，不关闭业务代码检查。
from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    # 来源只供员工追溯；客户检索只返回案例类型，绝不返回原工单或客户标识。
    source_kind: Mapped[str] = mapped_column(String(30), default="document", server_default="document")
    source_ticket_id: Mapped[UUID | None] = mapped_column(ForeignKey("tickets.id"), unique=True, nullable=True)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("staff_accounts.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    published: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    embedding_profile: Mapped[str] = mapped_column(String(64), default="", server_default="")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 草稿与线上切片分离；版本号防止两个员工覆盖彼此的预览和确认结果。
    draft_chunks: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list, server_default="[]")
    draft_warnings: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    draft_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    published_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    chunking_version: Mapped[str] = mapped_column(String(50), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("document_id", "position", name="uq_knowledge_chunk_position"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    heading_path: Mapped[str] = mapped_column(Text, default="", server_default="")
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 第一版采用精确向量检索，允许供应商维度变化；查询时严格匹配模型指纹。
    embedding: Mapped[list[float]] = mapped_column(Vector())
