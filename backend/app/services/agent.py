"""Oliveira 的最小有界 Agent Runtime。

运行时只拥有只读知识工具。工具结果和最终引用都写入 RunEvent/Run.output，
这样前端可以回放一次运行，也不会把模型输出当成事实源。
"""

import time
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.tables import Conversation, Message, Run
from app.services.agent_tools import ToolContext, build_default_registry
from app.services.llm import LLMNotConfigured, get_llm_for_scope
from app.services.run_events import append_run_event
from app.services.tasks import utc_now_naive


@dataclass
class AgentResult:
    answer: str
    citations: list[dict]
    steps: int


async def run_bounded_agent(
    db: AsyncSession,
    *,
    run: Run,
    conversation_id: UUID,
    question: str,
) -> AgentResult:
    settings = get_settings()
    started = time.monotonic()
    llm = await get_llm_for_scope(db, run.workspace_id, run.project_id)
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

    citations: list[dict] = []
    facts: list[dict] = []
    if run.project_id is not None:
        registry = build_default_registry()
        tool_context = ToolContext(db=db, project_id=run.project_id, run_id=run.id)
        search_args = {"query": question, "top_k": settings.retrieval_top_k}
        await append_run_event(db, run.id, "tool_call", {"tool": "search_chunks", "arguments": search_args})
        search_result = await registry.invoke("search_chunks", search_args, tool_context)
        citations = search_result.evidence
        await append_run_event(
            db,
            run.id,
            "tool_result",
            {
                "tool": "search_chunks",
                "count": len(citations),
                "evidence": citations,
                "elapsed_ms": search_result.elapsed_ms,
            },
        )

        if time.monotonic() - started > settings.max_agent_runtime_seconds:
            raise TimeoutError("Agent 超过最大运行时间")
        facts_args = {"query": question, "limit": 20}
        await append_run_event(db, run.id, "tool_call", {"tool": "query_facts", "arguments": facts_args})
        facts_result = await registry.invoke("query_facts", facts_args, tool_context)
        facts = facts_result.output["facts"]
        await append_run_event(
            db,
            run.id,
            "tool_result",
            {
                "tool": "query_facts",
                "count": len(facts),
                "facts": facts,
                "elapsed_ms": facts_result.elapsed_ms,
            },
        )
    else:
        await append_run_event(
            db,
            run.id,
            "scope_resolved",
            {"scope_type": "workspace", "project_id": None, "knowledge_tools": False},
        )

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
        f"当前知识范围：{'项目知识库' if run.project_id is not None else '工作空间通用对话'}\n"
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
                "content": (
                    "你是 Oliveira 的可信知识助手，只基于给定上下文回答。"
                    if run.project_id is not None
                    else "你是 Oliveira 的通用助手。当前没有选择知识项目，不要伪造知识库引用。"
                ),
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
    run.started_at = run.started_at or utc_now_naive()
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
        run.finished_at = utc_now_naive()
        conversation = await db.get(Conversation, run.conversation_id)
        if conversation is not None:
            conversation.updated_at = run.finished_at
        await append_run_event(db, run.id, "completed", {"citation_count": len(result.citations)})
        await db.commit()
        return {"status": "completed", "message_id": str(assistant.id)}
    except LLMNotConfigured:
        run.status = "failed"
        run.error = "Provider 未配置或不可用"
        run.finished_at = utc_now_naive()
        await append_run_event(db, run.id, "failed", {"code": "provider_not_configured"})
        await db.commit()
        raise
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)[:4000]
        run.finished_at = utc_now_naive()
        await append_run_event(db, run.id, "failed", {"error": run.error})
        await db.commit()
        raise
