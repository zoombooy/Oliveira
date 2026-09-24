from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_project_access
from app.core.config import get_settings
from app.core.database import get_session
from app.models.tables import Document, DocumentChunk, DocumentVersion, Run, User
from app.schemas.documents import DocumentDetailOut, DocumentOut, DocumentVersionOut
from app.services.ingest import UnsupportedFileType, chunk_paragraphs, parse_file, sha256_text
from app.services.llm import get_llm_for_project

router = APIRouter(prefix="/api/v1", tags=["documents"])


def _store_raw_file(project_id: UUID, document_id: UUID, version_no: int, filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower() or ".bin"
    if len(suffix) > 12 or not suffix[1:].isalnum():
        suffix = ".bin"
    rel_path = Path("uploads") / str(project_id) / str(document_id) / f"v{version_no}{suffix}"
    abs_path = Path(get_settings().data_dir) / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(data)
    return rel_path.as_posix()


async def _load_document(db: AsyncSession, document_id: UUID) -> tuple[Document, DocumentVersion]:
    document = await db.get(Document, document_id)
    if document is None or document.current_version_id is None:
        raise HTTPException(status_code=404, detail="文档或当前版本不存在")
    version = await db.get(DocumentVersion, document.current_version_id)
    if version is None:
        raise HTTPException(status_code=500, detail="文档缺少当前版本")
    return document, version


async def _embed_chunks(
    chunks: list, batch_size: int, db: AsyncSession, project_id: UUID
) -> tuple[list[list[float] | None], str]:
    """全量分批生成 embedding；任意批次失败时返回 partial，而不是伪装成功。"""
    if not chunks:
        return [], "unavailable"
    llm = await get_llm_for_project(db, project_id)
    if not llm.embedding_configured:
        return [None] * len(chunks), "unavailable"
    embeddings: list[list[float] | None] = [None] * len(chunks)
    try:
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            values = await llm.embed([chunk.content for chunk in batch])
            if values is None or len(values) != len(batch):
                return embeddings, "partial"
            embeddings[start : start + len(batch)] = values
    except Exception:
        return embeddings, "partial"
    return embeddings, "completed"


async def _create_version(
    project_id: UUID,
    document: Document,
    filename: str,
    mime_type: str,
    data: bytes,
    db: AsyncSession,
) -> tuple[DocumentVersion, int, str]:
    try:
        paragraphs = parse_file(filename, data)
    except UnsupportedFileType as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    settings = get_settings()
    chunks = chunk_paragraphs(paragraphs, size=settings.chunk_size, overlap=settings.chunk_overlap)
    full_text = "\n\n".join(piece[2] for piece in paragraphs)
    latest = (
        await db.execute(
            select(func.max(DocumentVersion.version_no)).where(
                DocumentVersion.document_id == document.id
            )
        )
    ).scalar_one()
    version_no = int(latest or 0) + 1
    version = DocumentVersion(
        document_id=document.id,
        version_no=version_no,
        file_name=filename,
        mime_type=mime_type,
        size_bytes=len(data),
        content_hash=sha256_text(full_text),
        parse_status="parsed",
        index_status="pending",
        object_key=_store_raw_file(project_id, document.id, version_no, filename, data),
    )
    db.add(version)
    await db.flush()
    document.current_version_id = version.id
    await db.flush()

    embeddings, index_status = await _embed_chunks(
        chunks, settings.embedding_batch_size, db, project_id
    )
    version.index_status = index_status
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        db.add(
            DocumentChunk(
                document_version_id=version.id,
                chunk_index=chunk.index,
                page_number=chunk.page_number,
                paragraph_index=chunk.paragraph_index,
                content=chunk.content,
                content_hash=sha256_text(chunk.content),
                token_count=chunk.token_count,
                embedding=embedding,
            )
        )
    db.add(
        Run(
            project_id=project_id,
            kind="ingest",
            status="completed",
            input={"filename": filename, "size_bytes": len(data), "version_no": version_no},
            output={"chunks": len(chunks), "index_status": index_status},
        )
    )
    await db.flush()
    return version, len(chunks), index_status


def _document_out(document: Document, version: DocumentVersion, chunk_count: int) -> DocumentOut:
    return DocumentOut(
        id=document.id,
        title=document.title,
        version_no=version.version_no,
        parse_status=version.parse_status,
        index_status=version.index_status,
        chunk_count=chunk_count,
        embedded=version.index_status in {"completed", "partial"},
        created_at=document.created_at,
    )


@router.post("/projects/{project_id}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    project_id: UUID,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> DocumentOut:
    await require_project_access(project_id, user, db, roles={"owner", "admin", "member"})
    data = await file.read()
    filename = file.filename or "untitled.txt"
    document = Document(project_id=project_id, title=filename)
    db.add(document)
    await db.flush()
    version, chunk_count, _ = await _create_version(
        project_id, document, filename, file.content_type or "", data, db
    )
    await db.commit()
    await db.refresh(document)
    await db.refresh(version)
    return _document_out(document, version, chunk_count)


@router.post("/documents/{document_id}/versions", response_model=DocumentOut, status_code=201)
async def upload_document_version(
    document_id: UUID,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> DocumentOut:
    document, _ = await _load_document(db, document_id)
    await require_project_access(document.project_id, user, db, roles={"owner", "admin", "member"})
    data = await file.read()
    filename = file.filename or "untitled.txt"
    version, chunk_count, _ = await _create_version(
        document.project_id, document, filename, file.content_type or "", data, db
    )
    await db.commit()
    await db.refresh(document)
    await db.refresh(version)
    return _document_out(document, version, chunk_count)


@router.get("/projects/{project_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[DocumentOut]:
    await require_project_access(project_id, user, db)
    stmt = (
        select(Document, DocumentVersion, func.count(DocumentChunk.id))
        .join(DocumentVersion, Document.current_version_id == DocumentVersion.id)
        .outerjoin(DocumentChunk, DocumentChunk.document_version_id == DocumentVersion.id)
        .where(Document.project_id == project_id)
        .group_by(Document.id, DocumentVersion.id)
        .order_by(Document.created_at)
    )
    return [_document_out(document, version, count) for document, version, count in (await db.execute(stmt)).all()]


@router.get("/documents/{document_id}/versions", response_model=list[DocumentVersionOut])
async def list_versions(
    document_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[DocumentVersion]:
    document, _ = await _load_document(db, document_id)
    await require_project_access(document.project_id, user, db)
    return list(
        (
            await db.execute(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document_id)
                .order_by(DocumentVersion.version_no.desc())
            )
        ).scalars()
    )


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
async def get_document(
    document_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> DocumentDetailOut:
    document, version = await _load_document(db, document_id)
    await require_project_access(document.project_id, user, db)
    chunk_count = (
        await db.execute(
            select(func.count(DocumentChunk.id)).where(DocumentChunk.document_version_id == version.id)
        )
    ).scalar_one()
    base = _document_out(document, version, chunk_count)
    return DocumentDetailOut(
        **base.model_dump(),
        project_id=document.project_id,
        file_name=version.file_name,
        size_bytes=version.size_bytes,
        content_hash=version.content_hash,
        object_key=version.object_key,
    )
