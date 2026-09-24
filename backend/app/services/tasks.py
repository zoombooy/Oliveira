from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Task


async def enqueue_task(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID | None,
    kind: str,
    payload: dict,
    max_attempts: int = 3,
) -> Task:
    task = Task(
        workspace_id=workspace_id,
        project_id=project_id,
        kind=kind,
        payload=payload,
        max_attempts=max_attempts,
    )
    db.add(task)
    await db.flush()
    return task


async def claim_task(db: AsyncSession, worker_id: str) -> Task | None:
    now = datetime.now(timezone.utc)
    stmt = (
        select(Task)
        .where(
            Task.status.in_(["queued", "retrying"]),
            Task.available_at <= now,
        )
        .order_by(Task.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task is None:
        return None
    task.status = "running"
    task.locked_by = worker_id
    task.locked_at = now
    task.started_at = task.started_at or now
    task.attempts += 1
    await db.commit()
    await db.refresh(task)
    return task


async def complete_task(db: AsyncSession, task_id: UUID, result: dict) -> None:
    task = await db.get(Task, task_id)
    if task is None:
        return
    task.status = "succeeded"
    task.result = result
    task.locked_by = None
    task.locked_at = None
    task.finished_at = datetime.now(timezone.utc)
    await db.commit()


async def fail_task(db: AsyncSession, task_id: UUID, error: str) -> None:
    task = await db.get(Task, task_id)
    if task is None:
        return
    task.last_error = error[:4000]
    task.locked_by = None
    task.locked_at = None
    if task.attempts >= task.max_attempts:
        task.status = "failed"
        task.finished_at = datetime.now(timezone.utc)
    else:
        task.status = "retrying"
        task.available_at = datetime.now(timezone.utc) + timedelta(seconds=min(60, 2**task.attempts))
    await db.commit()
