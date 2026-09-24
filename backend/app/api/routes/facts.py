from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_project_access
from app.core.database import get_session
from app.models.tables import AuditLog, Fact, FactVersion, ReviewItem, Task, User
from app.schemas.facts import ExtractFactsIn, FactOut, ResolveReviewIn, ReviewItemOut
from app.services.tasks import enqueue_task

router = APIRouter(prefix="/api/v1", tags=["facts"])


async def _fact_out(db: AsyncSession, fact: Fact) -> FactOut:
    version = await db.get(FactVersion, fact.current_version_id) if fact.current_version_id else None
    return FactOut(
        id=fact.id,
        project_id=fact.project_id,
        subject_text=fact.subject_text,
        predicate=fact.predicate,
        object_text=fact.object_text,
        status=fact.status,
        confidence=fact.confidence,
        valid_from=version.valid_from if version else None,
        valid_to=version.valid_to if version else None,
        recorded_at=version.recorded_at if version else None,
        evidence_ref_id=version.evidence_ref_id if version else None,
        created_at=fact.created_at,
    )


@router.post("/projects/{project_id}/facts/extract", status_code=202)
async def extract_facts(
    project_id: UUID,
    body: ExtractFactsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    project = await require_project_access(project_id, user, db, roles={"owner", "admin", "member"})
    task = await enqueue_task(
        db,
        workspace_id=project.workspace_id,
        project_id=project_id,
        kind="fact_extract",
        payload={"document_ids": [str(item) for item in body.document_ids]},
    )
    await db.commit()
    return {"task_id": str(task.id), "status": task.status}


@router.get("/projects/{project_id}/facts", response_model=list[FactOut])
async def list_facts(
    project_id: UUID,
    valid_at: datetime | None = None,
    recorded_at: datetime | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[FactOut]:
    await require_project_access(project_id, user, db)
    facts = list(
        (
            await db.execute(
                select(Fact).where(Fact.project_id == project_id).order_by(Fact.created_at.desc())
            )
        ).scalars()
    )
    result: list[FactOut] = []
    for fact in facts:
        item = await _fact_out(db, fact)
        if valid_at is not None and item.valid_from is not None:
            if valid_at < item.valid_from or (item.valid_to is not None and valid_at >= item.valid_to):
                continue
        if recorded_at is not None and item.recorded_at is not None and item.recorded_at > recorded_at:
            continue
        result.append(item)
    return result


@router.get("/projects/{project_id}/facts/{fact_id}", response_model=FactOut)
async def get_fact(
    project_id: UUID,
    fact_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> FactOut:
    await require_project_access(project_id, user, db)
    fact = await db.get(Fact, fact_id)
    if fact is None or fact.project_id != project_id:
        raise HTTPException(status_code=404, detail="事实不存在")
    return await _fact_out(db, fact)


@router.get("/projects/{project_id}/review-items", response_model=list[ReviewItemOut])
async def list_review_items(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[ReviewItem]:
    await require_project_access(project_id, user, db)
    return list(
        (
            await db.execute(
                select(ReviewItem)
                .where(ReviewItem.project_id == project_id, ReviewItem.status == "open")
                .order_by(ReviewItem.created_at)
            )
        ).scalars()
    )


async def _resolve_review(
    review_id: UUID,
    body: ResolveReviewIn,
    user: User,
    db: AsyncSession,
    approved: bool,
) -> ReviewItem:
    review = await db.get(ReviewItem, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="审核项不存在")
    await require_project_access(review.project_id, user, db, roles={"owner", "admin", "member"})
    if review.status != "open":
        raise HTTPException(status_code=409, detail="审核项已经处理")
    review.status = "resolved" if approved else "ignored"
    review.resolution = body.resolution
    review.resolved_by = f"user:{user.id}"
    review.resolved_at = datetime.now(timezone.utc)
    if review.item_type == "fact_pending":
        fact = await db.get(Fact, review.ref_id)
        if fact is not None:
            fact.status = "asserted" if approved else "rejected"
            db.add(
                AuditLog(
                    actor=f"user:{user.id}",
                    action="fact.approve" if approved else "fact.reject",
                    object_type="fact",
                    object_id=str(fact.id),
                    after={"status": fact.status},
                )
            )
    await db.commit()
    await db.refresh(review)
    return review


@router.post("/review-items/{review_id}/approve", response_model=ReviewItemOut)
async def approve_review(
    review_id: UUID,
    body: ResolveReviewIn | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ReviewItem:
    return await _resolve_review(review_id, body or ResolveReviewIn(), user, db, True)


@router.post("/review-items/{review_id}/reject", response_model=ReviewItemOut)
async def reject_review(
    review_id: UUID,
    body: ResolveReviewIn | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ReviewItem:
    return await _resolve_review(review_id, body or ResolveReviewIn(), user, db, False)


@router.post("/review-items/{review_id}/resolve", response_model=ReviewItemOut)
async def resolve_review(
    review_id: UUID,
    body: ResolveReviewIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ReviewItem:
    """保留一个显式 resolve 入口，默认按请求中的 resolution 仅关闭审核项。"""
    review = await db.get(ReviewItem, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="审核项不存在")
    await require_project_access(review.project_id, user, db, roles={"owner", "admin", "member"})
    if review.status != "open":
        raise HTTPException(status_code=409, detail="审核项已经处理")
    review.status = "resolved"
    review.resolution = body.resolution
    review.resolved_by = f"user:{user.id}"
    review.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(review)
    return review
