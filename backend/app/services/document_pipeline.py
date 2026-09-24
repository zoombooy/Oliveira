"""文档解析与 Embedding 的可恢复 Worker 管道。"""

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.tables import Document, DocumentChunk, DocumentVersion, Run, Task
from app.services.ingest import UnsupportedFileType, chunk_paragraphs, parse_file, sha256_text
from app.services.llm import get_llm_for_project
from app.services.object_storage import LocalObjectStorage
from app.services.run_events import append_run_event
from app.services.tasks import enqueue_task, utc_now_naive


class DocumentPipelineError(RuntimeError):
    retryable = True


class PermanentDocumentPipelineError(DocumentPipelineError):
    retryable = False


def _version_id(task: Task) -> UUID:
    return UUID(str(task.payload["version_id"]))


async def _load_version(db: AsyncSession, task: Task) -> tuple[DocumentVersion, Document, Run | None]:
    version = await db.get(DocumentVersion, _version_id(task))
    if version is None:
        raise PermanentDocumentPipelineError("文档版本不存在")
    document = await db.get(Document, version.document_id)
    if document is None:
        raise PermanentDocumentPipelineError("文档不存在")
    run_id = task.payload.get("run_id")
    run = await db.get(Run, UUID(str(run_id))) if run_id else None
    return version, document, run


async def _fail_run(db: AsyncSession, run: Run | None, event: str, error: str) -> None:
    if run is None:
        return
    run.status = "failed"
    run.error = error[:4000]
    run.finished_at = utc_now_naive()
    await append_run_event(db, run.id, event, {"error": run.error})


async def execute_document_ingest(db: AsyncSession, task: Task) -> dict:
    version, document, run = await _load_version(db, task)
    if version.parse_status == "parsed":
        await enqueue_task(
            db,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            kind="document_embed",
            payload={"version_id": str(version.id), "run_id": str(run.id) if run else None},
            dedupe_key=f"document_embed:{version.id}",
        )
        await db.commit()
        return {"version_id": str(version.id), "status": "already_parsed"}

    try:
        data = LocalObjectStorage().get_bytes(version.object_key)
        paragraphs = parse_file(version.file_name, data)
        chunks = chunk_paragraphs(
            paragraphs,
            size=get_settings().chunk_size,
            overlap=get_settings().chunk_overlap,
        )
    except (FileNotFoundError, UnsupportedFileType, UnicodeError) as exc:
        version.parse_status = "failed"
        version.index_status = "failed"
        version.parse_error = f"parse_error: {exc}"[:4000]
        await _fail_run(db, run, "failed", version.parse_error)
        await db.commit()
        raise PermanentDocumentPipelineError(version.parse_error) from exc
    except Exception as exc:
        version.parse_status = "failed"
        version.index_status = "failed"
        version.parse_error = f"parse_error: {exc}"[:4000]
        await _fail_run(db, run, "failed", version.parse_error)
        await db.commit()
        raise

    existing_count = int(
        (
            await db.execute(
                select(func.count(DocumentChunk.id)).where(
                    DocumentChunk.document_version_id == version.id
                )
            )
        ).scalar_one()
    )
    if existing_count != len(chunks):
        await db.execute(delete(DocumentChunk).where(DocumentChunk.document_version_id == version.id))
        for chunk in chunks:
            db.add(
                DocumentChunk(
                    document_version_id=version.id,
                    chunk_index=chunk.index,
                    page_number=chunk.page_number,
                    paragraph_index=chunk.paragraph_index,
                    content=chunk.content,
                    content_hash=sha256_text(chunk.content),
                    token_count=chunk.token_count,
                )
            )

    version.parse_status = "parsed"
    version.index_status = "pending" if chunks else "unavailable"
    version.parse_error = None
    await db.flush()
    if run is not None:
        run.status = "running"
        await append_run_event(
            db,
            run.id,
            "document_parsed",
            {"version_id": str(version.id), "chunk_count": len(chunks)},
        )
    await enqueue_task(
        db,
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        kind="document_embed",
        payload={"version_id": str(version.id), "run_id": str(run.id) if run else None},
        dedupe_key=f"document_embed:{version.id}",
    )
    await db.commit()
    return {"version_id": str(version.id), "status": "parsed", "chunk_count": len(chunks)}


async def execute_document_embed(db: AsyncSession, task: Task) -> dict:
    version, document, run = await _load_version(db, task)
    if version.parse_status != "parsed":
        raise DocumentPipelineError("文档尚未完成解析，不能执行 Embedding")
    chunks = list(
        (
            await db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_version_id == version.id)
                .order_by(DocumentChunk.chunk_index)
            )
        ).scalars()
    )
    if not chunks:
        version.index_status = "unavailable"
        if run is not None:
            run.status = "completed"
            run.output = {"version_id": str(version.id), "chunks": 0, "index_status": "unavailable"}
            run.finished_at = utc_now_naive()
            await append_run_event(db, run.id, "completed", run.output)
        await db.commit()
        return {"version_id": str(version.id), "chunks": 0, "index_status": "unavailable"}

    settings = get_settings()
    processed = 0
    try:
        llm = await get_llm_for_project(db, document.project_id)
        if not llm.embedding_configured:
            version.index_status = "unavailable"
            output = {
                "version_id": str(version.id),
                "chunks": len(chunks),
                "index_status": "unavailable",
            }
            if run is not None:
                run.status = "completed"
                run.output = output
                run.finished_at = utc_now_naive()
                await append_run_event(db, run.id, "completed", output)
            await db.commit()
            return output

        for start in range(0, len(chunks), settings.embedding_batch_size):
            batch = chunks[start : start + settings.embedding_batch_size]
            pending = [chunk for chunk in batch if chunk.embedding is None]
            if not pending:
                processed += len(batch)
                continue
            values = await llm.embed([chunk.content for chunk in pending])
            if values is None or len(values) != len(pending):
                raise DocumentPipelineError("embedding_response_count_mismatch")
            for chunk, embedding in zip(pending, values, strict=True):
                if len(embedding) != settings.embedding_dim:
                    raise PermanentDocumentPipelineError(
                        f"embedding_dimension_mismatch: expected {settings.embedding_dim}, got {len(embedding)}"
                    )
                chunk.embedding = embedding
            processed += len(batch)
            version.index_status = "partial"
            await db.commit()
    except Exception as exc:
        version.index_status = "partial" if processed else "failed"
        version.parse_error = f"embedding_error: {exc}"[:4000]
        if run is not None and (
            not getattr(exc, "retryable", True) or task.attempts >= task.max_attempts
        ):
            await _fail_run(db, run, "failed", version.parse_error)
        await db.commit()
        raise

    version.index_status = "completed"
    version.parse_error = None
    output = {"version_id": str(version.id), "chunks": len(chunks), "index_status": "completed"}
    if run is not None:
        run.status = "completed"
        run.output = output
        run.finished_at = utc_now_naive()
        await append_run_event(db, run.id, "completed", output)
    await db.commit()
    return output
