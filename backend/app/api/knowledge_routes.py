"""企业知识库管理入口：草稿只对员工可见，发布动作明确意味着资料可供客户问答。"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import require_staff
from app.db.knowledge_models import KnowledgeChunk, KnowledgeDocument
from app.db.session import get_db_session
from app.schema.access import Principal
from app.schema.knowledge import (
    DraftChunk,
    DraftRevision,
    DraftUpdate,
    KnowledgeChunkDetail,
    KnowledgeCreate,
    KnowledgeDetail,
    KnowledgeHit,
    KnowledgeSearch,
    KnowledgeSummary,
)
from app.services.knowledge_service import (
    KnowledgeConflictError,
    KnowledgeService,
    KnowledgeUnavailableError,
)

router = APIRouter(prefix="/api/v1/staff/knowledge", tags=["企业知识库"])
DB = Annotated[AsyncSession, Depends(get_db_session)]
Staff = Annotated[Principal, Depends(require_staff)]


def service(session: AsyncSession, staff: Principal) -> KnowledgeService:
    assert staff.company_id is not None
    return KnowledgeService(session, staff.company_id)


@router.get("", response_model=list[KnowledgeSummary])
async def documents(session: DB, staff: Staff, offset: Annotated[int, Query(ge=0)] = 0) -> list[KnowledgeSummary]:
    rows = await session.scalars(select(KnowledgeDocument).where(KnowledgeDocument.company_id == staff.company_id)
        .order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id).offset(offset).limit(20))
    return [KnowledgeSummary.model_validate(row) for row in rows]


@router.post("", response_model=KnowledgeSummary)
async def create(data: KnowledgeCreate, session: DB, staff: Staff) -> KnowledgeSummary:
    return KnowledgeSummary.model_validate(await service(session, staff).create(data))


@router.post("/upload", response_model=KnowledgeSummary)
async def upload(file: Annotated[UploadFile, File()], session: DB, staff: Staff) -> KnowledgeSummary:
    # 不保存客户提供的路径、不执行 Markdown；只接受有界 UTF-8 文本。
    filename = (file.filename or "").replace("\\", "/").split("/")[-1]
    try:
        if not filename.lower().endswith((".txt", ".md")):
            raise HTTPException(422, "第一版只支持 UTF-8 编码的 TXT/Markdown")
        raw = await file.read(240001)
        if len(raw) > 240000:
            raise HTTPException(413, "文件不能超过 240 KB")
        try:
            text = raw.decode("utf-8-sig").strip()
        except UnicodeDecodeError as exc:
            raise HTTPException(422, "请将文件转换为 UTF-8 编码") from exc
        if not text or len(text) > 60000 or "\x00" in text:
            raise HTTPException(422, "文件需为有效文本，正文长度为 1～60000 字符")
        return KnowledgeSummary.model_validate(await service(session, staff).create(KnowledgeCreate(title=filename[:200], content=text)))
    finally:
        await file.close()


@router.post("/search", response_model=list[KnowledgeHit])
async def search(data: KnowledgeSearch, session: DB, staff: Staff) -> list[KnowledgeHit]:
    try:
        return await service(session, staff).search(data.query)
    except KnowledgeUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/{id}", response_model=KnowledgeDetail)
async def detail(id: UUID, session: DB, staff: Staff) -> KnowledgeDetail:
    # 先验证企业归属再读取片段；返回真正入库的文本，不用临时分块冒充已发布索引。
    try:
        row = await service(session, staff).owned(id, lock=True)
        chunks = await session.scalars(select(KnowledgeChunk).where(
            KnowledgeChunk.document_id == id).order_by(KnowledgeChunk.position))
        return KnowledgeDetail(**KnowledgeSummary.model_validate(row).model_dump(),
            content=row.content, chunks=[KnowledgeChunkDetail.model_validate(chunk) for chunk in chunks],
            draft_chunks=[DraftChunk.model_validate(chunk) for chunk in row.draft_chunks], draft_revision=row.draft_revision,
            published_revision=row.published_revision, draft_warnings=row.draft_warnings)
    except LookupError as exc:
        raise HTTPException(404, "文档不存在") from exc


@router.post("/{id}/publish", response_model=KnowledgeSummary)
async def publish(id: UUID, data: DraftRevision, session: DB, staff: Staff) -> KnowledgeSummary:
    try:
        return KnowledgeSummary.model_validate(await service(session, staff).publish(id, data.revision))
    except LookupError as exc:
        raise HTTPException(404, "文档不存在") from exc
    except KnowledgeUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except KnowledgeConflictError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{id}/preview", response_model=KnowledgeSummary)
async def preview(id: UUID, data: DraftRevision, session: DB, staff: Staff) -> KnowledgeSummary:
    """重新生成会覆盖草稿，但不会替换线上知识；调用方须明确确认。"""
    try:
        return KnowledgeSummary.model_validate(await service(session, staff).prepare(id, data.revision))
    except LookupError as exc:
        raise HTTPException(404, "文档不存在") from exc
    except KnowledgeConflictError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.put("/{id}/draft", response_model=KnowledgeSummary)
async def save_draft(id: UUID, data: DraftUpdate, session: DB, staff: Staff) -> KnowledgeSummary:
    try:
        return KnowledgeSummary.model_validate(await service(session, staff).save_draft(id, data))
    except LookupError as exc:
        raise HTTPException(404, "文档不存在") from exc
    except KnowledgeConflictError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{id}/disable", response_model=KnowledgeSummary)
async def disable(id: UUID, session: DB, staff: Staff) -> KnowledgeSummary:
    try:
        row = await service(session, staff).owned(id, lock=True)
        row.published = False
        await session.commit()
        return KnowledgeSummary.model_validate(row)
    except LookupError as exc:
        raise HTTPException(404, "文档不存在") from exc
