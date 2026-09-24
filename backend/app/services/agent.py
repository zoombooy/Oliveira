"""Oliveira 的最小有界 Agent Runtime。

运行时只拥有只读知识工具。工具结果和最终引用都写入 RunEvent/Run.output，
这样前端可以回放一次运行，也不会把模型输出当成事实源。
"""

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.tables import Conversation, Fact, FactVersion, Message, Run
from app.services.llm import LLMNotConfigured, get_llm_for_project
from app.services.retrieval import RetrievedChunk, search
from app.services.run_events import append_run_event


@dataclass
class AgentResult:
    answer: str
    citations: list[dict]
    steps: int


def _citation_payload(item: RetrievedChunk) -> dict:
    return {
        "chunk_id": item.chunk_id,
        "document_id": item.document_id,
        "document_version_id": item.document_version_id,
        "document_title": item.document_title,
        "page_number": item.page_number,
        "paragraph_index": item.paragraph_index,
        "snippet": item.snippet[:500],
        "score": item.score,
        "method": item.method,
    }


async def _query_facts(db: AsyncSession, project_id: UUID, query: str) -> list[dict]:
    terms = [term for term in re.split(r"\s+", query.lower()) if len(term) >= 2][:6]
    stmt = select(Fact, FactVersion).join(FactVersion, Fact.current_version_id == FactVersion.id).where(
        Fact.project_id == project_id,
        Fact.status.in_(["asserted", "derived"]),
    )
    rows = (await db.execute(stmt)).all()
    results: list[dict] = []
    for fact, version in rows:
        text = f"{version.subject_text} {version.predicate} {version.object_text}".lower()
        if terms and not any(term in text for term in terms):
            continue
        results.append(
            {
                "fact_id": str(fact.id),
                "subject": version.subject_text,
                "predicate": version.predicate,
                "object": version.object_text,
                "valid_from": version.valid_from.isoformat() if version.valid_from else None,
                "valid_to": version.valid_to.isoformat() if version.valid_to else None,
                "recorded_at": version.recorded_at.isoformat(),
                "evidence_ref_id": str(version.evidence_ref_id) if version.evidence_ref_id else None,
            }
        )
    return results[:20]


async def run_bounded_agent(
    db: AsyncSession,
    *,
    run: Run,
    conversation_id: UUID,
    question: str,
) -> AgentResult:
    settings = get_settings()
    started = time.monotonic()
    llm = await get_llm_for_project(db, run.project_id)
    messages = list(
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(12)
            )
        ).scalars()
    )
    messages.reverse()

    await append_run_event(db, run.id, "tool_call", {"tool": "search_chunks", "arguments": {"query": question}})
    query_embedding = await llm.embed([question])
    retrieved = await search(
        db,
        run.project_id,
        question,
        top_k=settings.retrieval_top_k,
        query_embedding=query_embedding[0] if query_embedding else None,
    )
    citations = [_citation_payload(item) for item in retrieved]
    await append_run_event(
        db,
        run.id,
        "tool_result",
        {"tool": "search_chunks", "count": len(citations), "evidence": citations},
    )

    if time.monotonic() - started > settings.max_agent_runtime_seconds:
        raise TimeoutError("Agent 超过最大运行时间")
    await append_run_event(db, run.id, "tool_call", {"tool": "query_facts", "arguments": {"query": question}})
    facts = await _query_facts(db, run.project_id, question)
    await append_run_event(db, run.id, "tool_result", {"tool": "query_facts", "count": len(facts), "facts": facts})

    context = "\n\n".join(
        f"[{index}] {item['document_title']}"
        + (f" 第{item['page_number']}页" if item["page_number"] else "")
        + f"\n{item['snippet']}"
        for index, item in enumerate(citations, start=1)
    )
    fact_context = "\n".join(
        f"事实：{item['subject']} {item['predicate']} {item['object']}（记录于 {item['recorded_at']}）"
        for item in facts
    )
    history = "\n".join(f"{item.role}: {item.content}" for item in messages[-8:])
    prompt = (
        f"对话历史：\n{history}\n\n"
        f"证据块（只能引用这些编号）：\n{context or '无'}\n\n"
        f"已审核事实：\n{fact_context or '无'}\n\n"
        f"用户问题：{question}\n"
        "请用中文回答。凡是使用证据块中的内容，必须在对应句末使用 [1] 这样的编号；"
        "资料不足时要明确说明，不得补造来源。"
    )
    await append_run_event(db, run.id, "model_call", {"model": llm.model, "step": 1})
    answer = await llm.chat(
        [
            {
                "role": "system",
                "content": "你是 Oliveira 的可信知识助手，只基于给定上下文回答。",
            },
            {"role": "user", "content": prompt},
        ]
    )
    if time.monotonic() - started > settings.max_agent_runtime_seconds:
        raise TimeoutError("Agent 超过最大运行时间")

    references = [int(item) for item in re.findall(r"\[(\d+)\]", answer)]
    if any(reference < 1 or reference > len(citations) for reference in references):
        raise ValueError("回答未通过引用验证：存在本次 Run 未收集的引用编号")
    if citations and not references:
        answer = answer.rstrip() + "\n\n来源：" + " ".join(
            f"[{index}] {item['document_title']}" for index, item in enumerate(citations[:3], start=1)
        )
    await append_run_event(db, run.id, "citation_verified", {"references": references, "count": len(citations)})
    return AgentResult(answer=answer, citations=citations, steps=2)


async def execute_agent_run(db: AsyncSession, run_id: UUID) -> dict:
    run = await db.get(Run, run_id)
    if run is None:
        raise ValueError("Run 不存在")
    if run.status == "cancelled":
        return {"cancelled": True}
    if run.conversation_id is None:
        raise ValueError("Agent Run 缺少 conversation_id")
    run.status = "running"
    run.started_at = run.started_at or datetime.now(timezone.utc)
    await append_run_event(db, run.id, "started", {"max_steps": get_settings().max_agent_steps})
    await db.commit()
    try:
        result = await run_bounded_agent(
            db,
            run=run,
            conversation_id=run.conversation_id,
            question=str(run.input.get("question", "")),
        )
        assistant = Message(
            conversation_id=run.conversation_id,
            role="assistant",
            content=result.answer,
            run_id=run.id,
        )
        db.add(assistant)
        run.status = "completed"
        run.output = {"citations": result.citations, "steps": result.steps}
        run.finished_at = datetime.now(timezone.utc)
        conversation = await db.get(Conversation, run.conversation_id)
        if conversation is not None:
            conversation.updated_at = run.finished_at
        await append_run_event(db, run.id, "completed", {"citation_count": len(result.citations)})
        await db.commit()
        return {"status": "completed", "message_id": str(assistant.id)}
    except LLMNotConfigured:
        run.status = "failed"
        run.error = "Provider 未配置或不可用"
        run.finished_at = datetime.now(timezone.utc)
        await append_run_event(db, run.id, "failed", {"code": "provider_not_configured"})
        await db.commit()
        raise
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)[:4000]
        run.finished_at = datetime.now(timezone.utc)
        await append_run_event(db, run.id, "failed", {"error": run.error})
        await db.commit()
        raise
