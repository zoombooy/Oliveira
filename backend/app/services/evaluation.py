"""检索评估执行器。

评估只测“检索是否把标注来源召回”，不把 LLM 生成答案的主观质量
混进检索指标。每次运行保留用例级结果，便于比较切块、模型和权重变化。
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import EvaluationCase, EvaluationResult, EvaluationRun, Task
from app.services.llm import get_llm_for_project
from app.services.retrieval import search
from app.services.tasks import utc_now_naive


def first_relevant_rank(
    *,
    retrieved: list[tuple[str, str]],
    expected_chunk_ids: set[str],
    expected_document_ids: set[str],
) -> int | None:
    """返回第一个命中标注来源的 1-based 排名。"""
    for rank, (chunk_id, document_id) in enumerate(retrieved, start=1):
        if chunk_id in expected_chunk_ids or document_id in expected_document_ids:
            return rank
    return None


def aggregate_metrics(ranks: list[int | None], *, top_k: int) -> dict:
    total = len(ranks)
    hits = sum(rank is not None and rank <= top_k for rank in ranks)
    reciprocal_sum = sum(1.0 / rank for rank in ranks if rank is not None)
    return {
        "cases": total,
        "hit_at_k": round(hits / total, 6) if total else 0.0,
        "mrr": round(reciprocal_sum / total, 6) if total else 0.0,
        "top_k": top_k,
    }


async def execute_retrieval_evaluation(db: AsyncSession, task: Task) -> dict:
    run_id = UUID(str(task.payload["run_id"]))
    run = await db.get(EvaluationRun, run_id)
    if run is None:
        raise ValueError("评估 Run 不存在")

    top_k = int(run.config.get("top_k", 8))
    case_ids = [UUID(str(item)) for item in run.config.get("case_ids", [])]
    stmt = select(EvaluationCase).where(
        EvaluationCase.project_id == run.project_id,
        EvaluationCase.active.is_(True),
    )
    if case_ids:
        stmt = stmt.where(EvaluationCase.id.in_(case_ids))
    cases = list((await db.execute(stmt.order_by(EvaluationCase.created_at))).scalars())

    run.status = "running"
    run.started_at = utc_now_naive()
    run.total_cases = len(cases)
    await db.commit()

    llm = await get_llm_for_project(db, run.project_id)
    version_id = run.config.get("version_id")
    version_id = UUID(version_id) if version_id else None
    ranks: list[int | None] = []
    error_count = 0
    for case in cases:
        try:
            embedded = await llm.embed([case.question])
            query_embedding = embedded[0] if embedded else None
            results = await search(
                db,
                run.project_id,
                case.question,
                top_k=top_k,
                query_embedding=query_embedding,
                version_id=version_id,
            )
            retrieved = [(item.chunk_id, item.document_id) for item in results]
            rank = first_relevant_rank(
                retrieved=retrieved,
                expected_chunk_ids=set(case.expected_chunk_ids),
                expected_document_ids=set(case.expected_document_ids),
            )
            ranks.append(rank)
            db.add(
                EvaluationResult(
                    run_id=run.id,
                    case_id=case.id,
                    retrieved_chunk_ids=[item[0] for item in retrieved],
                    first_hit_rank=rank,
                    hit_at_k=rank is not None and rank <= top_k,
                    reciprocal_rank=1.0 / rank if rank else 0.0,
                )
            )
        except Exception as exc:
            error_count += 1
            ranks.append(None)
            db.add(
                EvaluationResult(
                    run_id=run.id,
                    case_id=case.id,
                    retrieved_chunk_ids=[],
                    first_hit_rank=None,
                    hit_at_k=False,
                    reciprocal_rank=0.0,
                    error=str(exc)[:4000],
                )
            )
        run.completed_cases += 1
        await db.commit()

    metrics = aggregate_metrics(ranks, top_k=top_k)
    metrics["error_cases"] = error_count
    metrics["successful_cases"] = len(cases) - error_count
    run.metrics = metrics
    run.status = "completed" if not error_count else "completed_with_errors"
    run.finished_at = utc_now_naive()
    await db.commit()
    return metrics
