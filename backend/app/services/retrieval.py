"""检索：向量（pgvector 余弦）优先，未配置嵌入模型时降级为关键词 ILIKE。"""

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Document, DocumentChunk, DocumentVersion


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_title: str
    page_number: int | None
    snippet: str
    score: float
    method: str  # vector | keyword


def _base_stmt(project_id: UUID):
    return (
        select(DocumentChunk, Document, DocumentVersion)
        .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .where(
            Document.project_id == project_id,
            DocumentVersion.parse_status == "parsed",
        )
    )


def _to_chunk(chunk: DocumentChunk, document: Document, score: float, method: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=str(chunk.id),
        document_id=str(document.id),
        document_title=document.title,
        page_number=chunk.page_number,
        snippet=chunk.content,
        score=score,
        method=method,
    )


async def search(
    db: AsyncSession,
    project_id: UUID,
    query: str,
    *,
    top_k: int,
    query_embedding: list[float] | None,
) -> list[RetrievedChunk]:
    if query_embedding is not None:
        return await _search_vector(db, project_id, query, top_k, query_embedding)
    return await _search_keyword(db, project_id, query, top_k)


async def _search_vector(
    db: AsyncSession,
    project_id: UUID,
    query: str,
    top_k: int,
    query_embedding: list[float],
) -> list[RetrievedChunk]:
    distance = DocumentChunk.embedding.cosine_distance(query_embedding).label("distance")
    stmt = (
        _base_stmt(project_id)
        .add_columns(distance)
        .where(DocumentChunk.embedding.is_not(None))
        .order_by(distance)
        .limit(top_k)
    )
    rows = (await db.execute(stmt)).all()
    results: list[RetrievedChunk] = []
    for chunk, document, _version, dist in rows:
        results.append(_to_chunk(chunk, document, 1.0 - float(dist), "vector"))
    return results


async def _search_keyword(
    db: AsyncSession,
    project_id: UUID,
    query: str,
    top_k: int,
) -> list[RetrievedChunk]:
    terms = [t for t in re.split(r"\s+", query.strip()) if len(t) >= 2][:5] or [query.strip()]
    stmt = _base_stmt(project_id).where(
        or_(*[DocumentChunk.content.ilike(f"%{t}%") for t in terms])
    ).limit(top_k)
    rows = (await db.execute(stmt)).all()
    return [
        _to_chunk(chunk, document, 1.0 / (rank + 1), "keyword")
        for rank, (chunk, document, _version) in enumerate(rows)
    ]
