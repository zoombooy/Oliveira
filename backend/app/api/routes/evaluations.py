from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_project_access
from app.core.database import get_session
from app.models.tables import EvaluationCase, EvaluationResult, EvaluationRun, User
from app.schemas.evaluations import (
    EvaluationCaseCreate,
    EvaluationCaseOut,
    EvaluationResultOut,
    EvaluationRunCreate,
    EvaluationRunOut,
)
from app.services.tasks import enqueue_task

router = APIRouter(prefix="/api/v1", tags=["evaluations"])


def _case_out(item: EvaluationCase) -> EvaluationCaseOut:
    return EvaluationCaseOut(
        id=item.id,
        project_id=item.project_id,
        question=item.question,
        expected_chunk_ids=list(item.expected_chunk_ids or []),
        expected_document_ids=list(item.expected_document_ids or []),
        reference_answer=item.reference_answer,
        metadata=dict(item.metadata_json or {}),
        active=item.active,
        created_at=item.created_at,
    )


def _run_out(item: EvaluationRun) -> EvaluationRunOut:
    return EvaluationRunOut(
        id=item.id,
        project_id=item.project_id,
        status=item.status,
        config=dict(item.config or {}),
        metrics=dict(item.metrics or {}),
        total_cases=item.total_cases,
        completed_cases=item.completed_cases,
        error=item.error,
        created_at=item.created_at,
        started_at=item.started_at,
        finished_at=item.finished_at,
    )


@router.post(
    "/projects/{project_id}/evaluation-cases",
    response_model=EvaluationCaseOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_evaluation_case(
    project_id: UUID,
    body: EvaluationCaseCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> EvaluationCaseOut:
    await require_project_access(project_id, user, db, roles={"owner", "admin", "member"})
    item = EvaluationCase(
        project_id=project_id,
        question=body.question,
        expected_chunk_ids=body.expected_chunk_ids,
        expected_document_ids=body.expected_document_ids,
        reference_answer=body.reference_answer,
        metadata_json=body.metadata,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _case_out(item)


@router.get("/projects/{project_id}/evaluation-cases", response_model=list[EvaluationCaseOut])
async def list_evaluation_cases(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[EvaluationCaseOut]:
    await require_project_access(project_id, user, db)
    items = list(
        (
            await db.execute(
                select(EvaluationCase)
                .where(EvaluationCase.project_id == project_id)
                .order_by(EvaluationCase.created_at)
            )
        ).scalars()
    )
    return [_case_out(item) for item in items]


@router.post("/projects/{project_id}/evaluations", response_model=EvaluationRunOut, status_code=202)
async def create_evaluation_run(
    project_id: UUID,
    body: EvaluationRunCreate | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> EvaluationRunOut:
    project = await require_project_access(project_id, user, db, roles={"owner", "admin", "member"})
    request = body or EvaluationRunCreate()
    item = EvaluationRun(
        project_id=project_id,
        status="queued",
        config={
            "case_ids": [str(case_id) for case_id in (request.case_ids or [])],
            "top_k": request.top_k,
            "version_id": str(request.version_id) if request.version_id else None,
        },
    )
    db.add(item)
    await db.flush()
    await enqueue_task(
        db,
        workspace_id=project.workspace_id,
        project_id=project_id,
        kind="retrieval_evaluation",
        payload={"run_id": str(item.id)},
        dedupe_key=f"retrieval_evaluation:{item.id}",
    )
    await db.commit()
    await db.refresh(item)
    return _run_out(item)


@router.get("/projects/{project_id}/evaluations", response_model=list[EvaluationRunOut])
async def list_evaluation_runs(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[EvaluationRunOut]:
    await require_project_access(project_id, user, db)
    items = list(
        (
            await db.execute(
                select(EvaluationRun)
                .where(EvaluationRun.project_id == project_id)
                .order_by(EvaluationRun.created_at.desc())
            )
        ).scalars()
    )
    return [_run_out(item) for item in items]


@router.get("/evaluations/{run_id}", response_model=EvaluationRunOut)
async def get_evaluation_run(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> EvaluationRunOut:
    item = await db.get(EvaluationRun, run_id)
    if item is None:
        raise HTTPException(status_code=404, detail="评估 Run 不存在")
    await require_project_access(item.project_id, user, db)
    return _run_out(item)


@router.get("/evaluations/{run_id}/results", response_model=list[EvaluationResultOut])
async def list_evaluation_results(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[EvaluationResultOut]:
    run = await db.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评估 Run 不存在")
    await require_project_access(run.project_id, user, db)
    items = list(
        (
            await db.execute(
                select(EvaluationResult)
                .where(EvaluationResult.run_id == run_id)
                .order_by(EvaluationResult.created_at)
            )
        ).scalars()
    )
    return [
        EvaluationResultOut(
            id=item.id,
            run_id=item.run_id,
            case_id=item.case_id,
            retrieved_chunk_ids=list(item.retrieved_chunk_ids or []),
            first_hit_rank=item.first_hit_rank,
            hit_at_k=item.hit_at_k,
            reciprocal_rank=item.reciprocal_rank,
            error=item.error,
            created_at=item.created_at,
        )
        for item in items
    ]
