"""向量 + pg_trgm/关键词混合检索。"""

import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.tables import Document, DocumentChunk, DocumentVersion


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_version_id: str
    document_title: str
    page_number: int | None
    paragraph_index: int | None
    snippet: str
    score: float
    vector_score: float | None = None
    keyword_score: float | None = None
    methods: list[str] = field(default_factory=list)

    @property
    def method(self) -> str:
        return "+".join(self.methods) or "none"


def _base_stmt(project_id: UUID, version_id: UUID | None = None):
    stmt = (
        select(DocumentChunk, Document, DocumentVersion)
        .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .where(Document.project_id == project_id, DocumentVersion.parse_status == "parsed")
    )
    if version_id is not None:
        stmt = stmt.where(DocumentVersion.id == version_id)
    return stmt


def _to_chunk(
    chunk: DocumentChunk,
    document: Document,
    version: DocumentVersion,
    *,
    final_score: float,
    vector_score: float | None,
    keyword_score: float | None,
    methods: list[str],
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=str(chunk.id),
        document_id=str(document.id),
        document_version_id=str(version.id),
        document_title=document.title,
        page_number=chunk.page_number,
        paragraph_index=chunk.paragraph_index,
        snippet=chunk.content,
        score=final_score,
        vector_score=vector_score,
        keyword_score=keyword_score,
        methods=methods,
    )


async def search(
    db: AsyncSession,
    project_id: UUID,
    query: str,
    *,
    top_k: int,
    query_embedding: list[float] | None,
    version_id: UUID | None = None,
) -> list[RetrievedChunk]:
    settings = get_settings()
    limit = max(top_k * 2, top_k)
    try:
        vector_rows = await _search_vector(db, project_id, query_embedding, limit, version_id)
    except Exception:
        # Embedding 维度不匹配或索引暂时不可用时，关键词检索仍然应该可用。
        await db.rollback()
        vector_rows = []
    keyword_rows = await _search_keyword(db, project_id, query, limit, version_id)
    merged: dict[str, RetrievedChunk] = {}
    for item in vector_rows:
        merged[item.chunk_id] = item
    for item in keyword_rows:
        existing = merged.get(item.chunk_id)
        if existing is None:
            merged[item.chunk_id] = item
            continue
        existing.keyword_score = item.keyword_score
        existing.methods = sorted(set(existing.methods + item.methods))
        existing.score = round(
            settings.vector_weight * (existing.vector_score or 0.0)
            + settings.keyword_weight * (existing.keyword_score or 0.0),
            6,
        )
    for item in merged.values():
        if item.methods == ["keyword"]:
            item.score = item.keyword_score or 0.0
        elif item.methods == ["vector"]:
            item.score = item.vector_score or 0.0
    return sorted(merged.values(), key=lambda item: item.score, reverse=True)[:top_k]


async def _search_vector(
    db: AsyncSession,
    project_id: UUID,
    query_embedding: list[float] | None,
    limit: int,
    version_id: UUID | None,
) -> list[RetrievedChunk]:
    if query_embedding is None:
        return []
    distance = DocumentChunk.embedding.cosine_distance(query_embedding).label("distance")
    stmt = (
        _base_stmt(project_id, version_id)
        .add_columns(distance)
        .where(DocumentChunk.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        _to_chunk(
            chunk,
            document,
            version,
            final_score=max(0.0, 1.0 - float(distance_value)),
            vector_score=max(0.0, 1.0 - float(distance_value)),
            keyword_score=None,
            methods=["vector"],
        )
        for chunk, document, version, distance_value in rows
    ]


async def _search_keyword(
    db: AsyncSession,
    project_id: UUID,
    query: str,
    limit: int,
    version_id: UUID | None,
) -> list[RetrievedChunk]:
    clean_query = query.strip()
    if not clean_query:
        return []
    try:
        similarity = func.similarity(DocumentChunk.content, clean_query).label("similarity")
        stmt = (
            _base_stmt(project_id, version_id)
            .add_columns(similarity)
            .where(similarity > 0)
            .order_by(similarity.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()
    except Exception:
        await db.rollback()
        terms = [term for term in re.split(r"\s+", clean_query) if len(term) >= 2][:5]
        terms = terms or [clean_query]
        stmt = (
            _base_stmt(project_id, version_id)
            .where(or_(*[DocumentChunk.content.ilike(f"%{term}%") for term in terms]))
            .limit(limit)
        )
        rows = [(chunk, document, version, 1.0 / (index + 1)) for index, (chunk, document, version) in enumerate((await db.execute(stmt)).all())]
    return [
        _to_chunk(
            chunk,
            document,
            version,
            final_score=float(score),
            vector_score=None,
            keyword_score=float(score),
            methods=["keyword"],
        )
        for chunk, document, version, score in rows
    ]
