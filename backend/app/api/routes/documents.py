from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.models.tables import Document, DocumentChunk, DocumentVersion, Run
from app.schemas.documents import DocumentDetailOut, DocumentOut
from app.services.ingest import UnsupportedFileType, chunk_paragraphs, parse_file, sha256_text
from app.services.llm import get_llm

router = APIRouter(prefix="/api/v1", tags=["documents"])

# 单次入库嵌入的 chunk 上限，防止大文档拖垮嵌入预算；未嵌入的块走关键词降级
_EMBED_BATCH_LIMIT = 64


async def _load_document(db: AsyncSession, document_id) -> tuple[Document, DocumentVersion]:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    version = await db.get(DocumentVersion, document.current_version_id)
    if version is None:
        raise HTTPException(status_code=500, detail="文档缺少当前版本")
    return document, version


def _store_raw_file(project_id, document_id, version_no: int, filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix or ".bin"
    rel_dir = Path("uploads") / str(project_id) / str(document_id)
    rel_path = rel_dir / f"v{version_no}{suffix}"
    abs_path = Path(get_settings().data_dir) / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(data)
    return rel_path.as_posix()


@router.post("/projects/{project_id}/documents", response_model=DocumentOut)
async def upload_document(
    project_id,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session),
) -> DocumentOut:
    from app.models.tables import Project

    if await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    data = await file.read()
    filename = file.filename or "untitled.txt"
    try:
        paragraphs = parse_file(filename, data)
    except UnsupportedFileType as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    settings = get_settings()
    chunks = chunk_paragraphs(
        paragraphs, size=settings.chunk_size, overlap=settings.chunk_overlap
    )
    full_text = "\n\n".join(p[2] for p in paragraphs)

    document = Document(project_id=project_id, title=filename)
    db.add(document)
    await db.flush()

    version_no = 1
    version = DocumentVersion(
        document_id=document.id,
        version_no=version_no,
        file_name=filename,
        mime_type=file.content_type or "",
        size_bytes=len(data),
        content_hash=sha256_text(full_text),
        parse_status="parsed",
        object_key=_store_raw_file(project_id, document.id, version_no, filename, data),
    )
    db.add(version)
    document.current_version_id = version.id
    await db.flush()

    embeddings = await get_llm().embed([c.content for c in chunks[:_EMBED_BATCH_LIMIT]])
    embedded = embeddings is not None
    for chunk in chunks:
        embedding = None
        if embedded and chunk.index < _EMBED_BATCH_LIMIT:
            embedding = embeddings[chunk.index]
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
            input={"filename": filename, "size_bytes": len(data)},
            output={"chunks": len(chunks), "embedded": embedded},
            started_at=version.created_at,
        )
    )
    await db.commit()
    return DocumentOut(
        id=document.id,
        title=document.title,
        version_no=version_no,
        parse_status=version.parse_status,
        chunk_count=len(chunks),
        embedded=embedded,
        created_at=document.created_at,
    )


@router.get("/projects/{project_id}/documents", response_model=list[DocumentOut])
async def list_documents(project_id, db: AsyncSession = Depends(get_session)) -> list[DocumentOut]:
    stmt = (
        select(Document, DocumentVersion, func.count(DocumentChunk.id))
        .join(DocumentVersion, Document.current_version_id == DocumentVersion.id)
        .join(DocumentChunk, DocumentChunk.document_version_id == DocumentVersion.id)
        .where(Document.project_id == project_id)
        .group_by(Document.id, DocumentVersion.id)
        .order_by(Document.created_at)
    )
    rows = (await db.execute(stmt)).all()

    embedded_version_ids: set = set(
        (
            await db.execute(
                select(DocumentChunk.document_version_id)
                .where(DocumentChunk.embedding.is_not(None))
                .distinct()
            )
        ).scalars()
    )

    return [
        DocumentOut(
            id=document.id,
            title=document.title,
            version_no=version.version_no,
            parse_status=version.parse_status,
            chunk_count=chunk_count,
            embedded=version.id in embedded_version_ids,
            created_at=document.created_at,
        )
        for document, version, chunk_count in rows
    ]


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
async def get_document(document_id, db: AsyncSession = Depends(get_session)) -> DocumentDetailOut:
    document, version = await _load_document(db, document_id)
    chunk_count = (
        await db.execute(
            select(func.count(DocumentChunk.id)).where(
                DocumentChunk.document_version_id == version.id
            )
        )
    ).scalar_one()
    return DocumentDetailOut(
        id=document.id,
        project_id=document.project_id,
        title=document.title,
        version_no=version.version_no,
        parse_status=version.parse_status,
        chunk_count=chunk_count,
        embedded=True,
        created_at=document.created_at,
        file_name=version.file_name,
        size_bytes=version.size_bytes,
        content_hash=version.content_hash,
        object_key=version.object_key,
    )
