"""从已解析文档生成待审核事实。

模型只能提交结构化候选，发布状态仍由审核接口决定。每个候选必须指向真实
chunk；无法校验证据的模型输出会被丢弃，不会进入事实表。
"""

import json
import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.tables import (
    Document,
    DocumentChunk,
    DocumentVersion,
    EvidenceRef,
    Fact,
    FactConflict,
    FactEvidence,
    FactVersion,
    Project,
    ReviewItem,
    Task,
)
from app.services.llm import get_llm_for_project


class ExtractedEvidence(BaseModel):
    chunk_id: UUID
    quote: str = Field(default="", max_length=4000)
    location: dict = Field(default_factory=dict)


class ExtractedFact(BaseModel):
    subject_text: str = Field(min_length=1, max_length=2000)
    predicate: str = Field(min_length=1, max_length=1000)
    object_text: str = Field(min_length=1, max_length=4000)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: list[ExtractedEvidence] = Field(min_length=1, max_length=8)


class ExtractedFacts(BaseModel):
    facts: list[ExtractedFact] = Field(default_factory=list, max_length=100)


def _parse_json(text: str) -> dict:
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.IGNORECASE | re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("事实抽取结果不是 JSON")
    return json.loads(candidate[start : end + 1])


async def execute_fact_extract(db: AsyncSession, task: Task) -> dict:
    project = await db.get(Project, task.project_id)
    if project is None:
        raise ValueError("事实抽取项目不存在")
    requested_ids = [UUID(item) for item in task.payload.get("document_ids", [])]
    version_stmt = (
        select(DocumentVersion, Document)
        .join(Document, DocumentVersion.document_id == Document.id)
        .where(Document.project_id == project.id)
    )
    if requested_ids:
        version_stmt = version_stmt.where(Document.id.in_(requested_ids))
    versions = (await db.execute(version_stmt.order_by(Document.created_at))).all()
    if not versions:
        return {"facts": 0, "documents": 0}
    chunks_stmt = (
        select(DocumentChunk, Document, DocumentVersion)
        .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .where(Document.project_id == project.id)
    )
    if requested_ids:
        chunks_stmt = chunks_stmt.where(Document.id.in_(requested_ids))
    chunk_rows = (await db.execute(chunks_stmt.order_by(Document.created_at, DocumentChunk.chunk_index))).all()
    if not chunk_rows:
        return {"facts": 0, "documents": len(versions)}
    excerpt = "\n\n".join(
        f"chunk_id={chunk.id} document={document.title} page={chunk.page_number or ''}\n{chunk.content[:2500]}"
        for chunk, document, _version in chunk_rows
    )
    llm = await get_llm_for_project(db, project.id)
    prompt = (
        "从下面的资料中抽取可被原文支持的事实，严格只返回 JSON，不要 Markdown。"
        "每条事实必须引用一个或多个真实 chunk_id；没有充分证据就不要抽取。"
        "JSON 结构：{\"facts\":[{\"subject_text\":\"\",\"predicate\":\"\","
        "\"object_text\":\"\",\"valid_from\":null,\"valid_to\":null,"
        "\"confidence\":0.0,\"evidence\":[{\"chunk_id\":\"uuid\",\"quote\":\"\","
        "\"location\":{}}]}]}\n\n资料：\n" + excerpt
    )
    raw = await llm.chat(
        [
            {"role": "system", "content": "你是严格的知识抽取器，只输出符合要求的 JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    try:
        extracted = ExtractedFacts.model_validate(_parse_json(raw))
    except (ValueError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"事实抽取输出无法校验: {exc}") from exc

    chunk_by_id = {chunk.id: (chunk, document, version) for chunk, document, version in chunk_rows}
    created = 0
    conflicts = 0
    for item in extracted.facts:
        evidence = next((candidate for candidate in item.evidence if candidate.chunk_id in chunk_by_id), None)
        if evidence is None:
            continue
        chunk, document, version = chunk_by_id[evidence.chunk_id]
        existing = (
            await db.execute(
                select(Fact).where(
                    Fact.project_id == project.id,
                    Fact.subject_text == item.subject_text,
                    Fact.predicate == item.predicate,
                    Fact.object_text == item.object_text,
                    Fact.status.not_in(["rejected", "retracted"]),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        evidence_ref = EvidenceRef(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            chunk_id=chunk.id,
            quote=evidence.quote or chunk.content[:1000],
            location=evidence.location or {
                "page_number": chunk.page_number,
                "paragraph_index": chunk.paragraph_index,
            },
            observed_at=version.created_at,
            snapshot_hash=chunk.content_hash,
        )
        db.add(evidence_ref)
        await db.flush()
        fact = Fact(
            project_id=project.id,
            subject_text=item.subject_text,
            predicate=item.predicate,
            object_text=item.object_text,
            status="pending",
            confidence=item.confidence,
            created_by="system:fact_extract",
        )
        db.add(fact)
        await db.flush()
        fact_version = FactVersion(
            fact_id=fact.id,
            version_no=1,
            subject_text=item.subject_text,
            predicate=item.predicate,
            object_text=item.object_text,
            valid_from=item.valid_from,
            valid_to=item.valid_to,
            evidence_ref_id=evidence_ref.id,
            change_reason="自动抽取，待审核",
        )
        db.add(fact_version)
        await db.flush()
        fact.current_version_id = fact_version.id
        db.add(FactEvidence(fact_version_id=fact_version.id, evidence_ref_id=evidence_ref.id))
        db.add(
            ReviewItem(
                project_id=project.id,
                item_type="fact_pending",
                ref_id=fact.id,
                reason=("置信度低于 0.75" if item.confidence < 0.75 else "自动抽取事实待人工确认"),
            )
        )
        created += 1

        conflict_stmt = select(Fact).where(
            Fact.project_id == project.id,
            Fact.id != fact.id,
            Fact.subject_text == item.subject_text,
            Fact.predicate == item.predicate,
            Fact.object_text != item.object_text,
            Fact.status.not_in(["rejected", "retracted"]),
        )
        for conflicting in (await db.execute(conflict_stmt)).scalars():
            db.add(
                FactConflict(
                    project_id=project.id,
                    fact_id=fact.id,
                    conflicting_fact_id=conflicting.id,
                    conflict_type="same_subject_predicate_different_object",
                )
            )
            conflicts += 1
    await db.commit()
    return {"facts": created, "conflicts": conflicts, "documents": len(versions)}
