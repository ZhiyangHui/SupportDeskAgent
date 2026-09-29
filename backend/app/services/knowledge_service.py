"""知识库索引与检索：模型隔离、企业授权、原子发布以及有界外部调用。"""
import asyncio
import hashlib
import math
from functools import lru_cache
from uuid import UUID

from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr
from sqlalchemy import case, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.knowledge_models import KnowledgeChunk, KnowledgeDocument
from app.schema.knowledge import DraftChunk, DraftUpdate, KnowledgeCreate, KnowledgeHit
from app.services.knowledge_chunking import CHUNKING_VERSION, build_draft, indexed_text


class KnowledgeUnavailableError(ValueError):
    """知识服务不可用时向用户提供稳定说明，不输出供应商响应或密钥。"""


class KnowledgeConflictError(ValueError):
    """草稿变化后必须重新查看，不能隐式发布员工尚未确认的内容。"""


def embedding_profile() -> str:
    config = get_settings()
    return hashlib.sha256(f"{config.embedding_base_url.rstrip('/')}|{config.embedding_model}|{config.embedding_dimensions}".encode()).hexdigest()


@lru_cache
def embedding_client() -> OpenAIEmbeddings:
    config = get_settings()
    if not config.knowledge_enabled or not all((config.embedding_api_key, config.embedding_base_url, config.embedding_model)):
        raise KnowledgeUnavailableError("知识库向量服务未启用或未配置，请配置独立的 Embedding 服务。")
    # 第三方兼容接口发送原始文本，不发送 OpenAI 的 token 编号；不假设支持 dimensions 参数。
    return OpenAIEmbeddings(model=config.embedding_model, api_key=SecretStr(config.embedding_api_key),
        base_url=config.embedding_base_url, check_embedding_ctx_length=False,
        model_kwargs={"encoding_format": "float"}, timeout=25, max_retries=0, chunk_size=16)


def validate_vectors(vectors: list[list[float]], count: int) -> None:
    if len(vectors) != count or any(len(v) != get_settings().embedding_dimensions or
        not all(math.isfinite(x) for x in v) or not any(v) for v in vectors):
        raise KnowledgeUnavailableError("向量数量、维度或数值不符合配置，索引未发布。")


class KnowledgeService:
    def __init__(self, session: AsyncSession, company_id: UUID):
        self.session, self.company_id = session, company_id

    async def owned(self, id: UUID, lock: bool = False) -> KnowledgeDocument:
        query = select(KnowledgeDocument).where(KnowledgeDocument.id == id, KnowledgeDocument.company_id == self.company_id)
        if lock:
            query = query.with_for_update()
        row = await self.session.scalar(query.execution_options(populate_existing=True))
        if row is None:
            raise LookupError("知识文档不存在")
        return row

    async def create(self, data: KnowledgeCreate) -> KnowledgeDocument:
        # 保存草稿不会调用收费服务；只有员工明确点击发布才发送资料进行向量化。
        row = KnowledgeDocument(company_id=self.company_id, title=data.title, content=data.content)
        self.session.add(row)
        await self.session.commit()
        return row

    async def prepare(self, id: UUID, revision: int) -> KnowledgeDocument:
        row = await self.owned(id, lock=True)
        self.check_revision(row, revision)
        chunks, warnings = build_draft(row.title, row.content)
        if not chunks or len(chunks) > 300:
            raise KnowledgeConflictError("未生成有效分块或分块超过 300 个，请调整原文。")
        row.draft_chunks = [chunk.model_dump() for chunk in chunks]
        row.draft_warnings = warnings
        row.draft_revision += 1
        row.chunking_version = CHUNKING_VERSION
        await self.session.commit()
        return row

    @staticmethod
    def check_revision(row: KnowledgeDocument, revision: int) -> None:
        if row.draft_revision != revision:
            raise KnowledgeConflictError("草稿已被更新，请重新加载并确认后操作。")

    async def save_draft(self, id: UUID, data: DraftUpdate) -> KnowledgeDocument:
        row = await self.owned(id, lock=True)
        self.check_revision(row, data.revision)
        if sum(len(chunk.content) for chunk in data.chunks) > 120000:
            raise KnowledgeConflictError("草稿正文总量超过限制，请减少重复内容。")
        row.draft_chunks = [chunk.model_dump() for chunk in data.chunks]
        row.draft_revision += 1
        # 手动调整仍需保留自动识别警告，避免误导为已通过语义审查。
        await self.session.commit()
        return row

    async def publish(self, id: UUID, revision: int) -> KnowledgeDocument:
        try:
            # 第一版小文档同步索引且超时受限；同行写锁避免发布/停用互相覆盖。
            async with asyncio.timeout(35):
                row = await self.owned(id, lock=True)
                self.check_revision(row, revision)
                if not row.draft_chunks:
                    raise KnowledgeConflictError("请先生成并查看待发布分块，再确认发布。")
                profile = embedding_profile()
                drafts = [DraftChunk.model_validate(chunk) for chunk in row.draft_chunks]
                chunks = [indexed_text(chunk.heading_path, chunk.content) for chunk in drafts]
                if not chunks or len(chunks) > 300:
                    raise KnowledgeUnavailableError("文档切片数量超限，请拆成更小的文档。")
                # 同时比较实际片段，避免调整分块规则后仍复用旧的大块索引。
                saved = list(await self.session.scalars(select(KnowledgeChunk)
                    .where(KnowledgeChunk.document_id == id).order_by(KnowledgeChunk.position)))
                existing = [indexed_text(chunk.heading_path, chunk.content) for chunk in saved]
                if row.chunk_count and row.embedding_profile == profile and existing == chunks:
                    row.published = True
                    for chunk in saved:
                        chunk.version = revision
                else:
                    vectors = await embedding_client().aembed_documents(chunks)
                    validate_vectors(vectors, len(chunks))
                    # 新切片全部准备完成后才替换，失败回滚会保留原来可用的索引。
                    await self.session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == id))
                    self.session.add_all([KnowledgeChunk(document_id=id, position=i + 1,
                        content=chunk.content, heading_path=chunk.heading_path, version=revision, embedding=vector)
                        for i, (chunk, vector) in enumerate(zip(drafts, vectors, strict=True))])
                    row.chunk_count, row.embedding_profile, row.published = len(chunks), profile, True
                row.published_revision = revision
                await self.session.commit()
                return row
        except (LookupError, KnowledgeUnavailableError, KnowledgeConflictError):
            await self.session.rollback()
            raise
        except Exception as exc:
            await self.session.rollback()
            raise KnowledgeUnavailableError("向量索引失败，原有数据未改变。请检查 Embedding 配置并重试。") from exc

    async def search(self, query: str) -> list[KnowledgeHit]:
        # 构造客户端仅验证配置，不发送网络请求；未配置与检索无结果是两种不同反馈。
        client = embedding_client()
        # 先检查有无当前模型可用资料，空知识库不浪费向量请求，也不降级为模型编造。
        profile = embedding_profile()
        filters = [KnowledgeDocument.company_id == self.company_id, KnowledgeDocument.published.is_(True), KnowledgeDocument.embedding_profile == profile]
        if not await self.session.scalar(select(KnowledgeDocument.id).where(*filters).limit(1)):
            return []
        try:
            async with asyncio.timeout(30):
                vector = await client.aembed_query(query)
                validate_vectors([vector], 1)
        except KnowledgeUnavailableError:
            raise
        except Exception as exc:
            raise KnowledgeUnavailableError("知识检索服务暂不可用，请稍后重试或联系人工客服。") from exc
        # CASE 防止查询优化器先对其他模型维度执行距离运算；企业条件仍在 SQL 层强制过滤。
        distance = case((KnowledgeDocument.embedding_profile == profile, KnowledgeChunk.embedding.cosine_distance(vector)), else_=None).label("distance")
        rows = await self.session.execute(select(KnowledgeChunk, KnowledgeDocument.title, distance)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id).where(*filters)
            .order_by(distance, KnowledgeChunk.id).limit(5))
        return [KnowledgeHit(document_id=chunk.document_id, chunk_id=chunk.id, title=title,
            position=chunk.position, content=indexed_text(chunk.heading_path, chunk.content), score=round(1 - score, 5))
            for chunk, title, score in rows if score is not None and 1 - score >= get_settings().knowledge_min_score]
