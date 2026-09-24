from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_project_access, require_workspace_member
from app.core.database import get_session
from app.models.tables import Run, RunEvent, User
from app.schemas.runs import RunEventOut, RunOut
from app.services.tasks import enqueue_task, utc_now_naive

router = APIRouter(prefix="/api/v1", tags=["runs"])


async def _load_run(db: AsyncSession, run_id: UUID, user: User) -> Run:
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run 不存在")
    if run.project_id is not None:
        project = await require_project_access(run.project_id, user, db)
        if project.workspace_id != run.workspace_id:
            raise HTTPException(status_code=409, detail="Run 作用域与项目工作空间不一致")
    else:
        await require_workspace_member(run.workspace_id, user, db)
    return run


@router.get("/runs", response_model=list[RunOut])
async def list_runs(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[Run]:
    await require_project_access(project_id, user, db)
    stmt = select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc())
    return list((await db.execute(stmt)).scalars())


@router.get("/workspaces/{workspace_id}/runs", response_model=list[RunOut])
async def list_workspace_runs(
    workspace_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[Run]:
    await require_workspace_member(workspace_id, user, db)
    stmt = select(Run).where(Run.workspace_id == workspace_id).order_by(Run.created_at.desc())
    return list((await db.execute(stmt)).scalars())


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Run:
    return await _load_run(db, run_id, user)


@router.get("/runs/{run_id}/events", response_model=list[RunEventOut])
async def list_run_events(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[RunEvent]:
    await _load_run(db, run_id, user)
    return list(
        (
            await db.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq))
        ).scalars()
    )


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Run:
    run = await _load_run(db, run_id, user)
    if run.status in {"completed", "failed", "cancelled"}:
        return run
    run.status = "cancelled"
    run.finished_at = utc_now_naive()
    next_seq = (
        await db.execute(select(func.coalesce(func.max(RunEvent.seq), 0) + 1).where(RunEvent.run_id == run.id))
    ).scalar_one()
    db.add(RunEvent(run_id=run.id, seq=next_seq, event_type="cancelled", payload={}))
    await db.commit()
    await db.refresh(run)
    return run


@router.post("/runs/{run_id}/resume", response_model=RunOut)
async def resume_run(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Run:
    run = await _load_run(db, run_id, user)
    if run.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="当前 Run 不允许恢复")
    run.status = "queued"
    run.error = None
    run.finished_at = None
    next_seq = (
        await db.execute(select(func.coalesce(func.max(RunEvent.seq), 0) + 1).where(RunEvent.run_id == run.id))
    ).scalar_one()
    db.add(RunEvent(run_id=run.id, seq=next_seq, event_type="resumed", payload={}))
    if run.project_id is not None:
        project = await require_project_access(run.project_id, user, db)
        workspace_id = project.workspace_id
    else:
        await require_workspace_member(run.workspace_id, user, db)
        workspace_id = run.workspace_id
    if run.kind == "chat" and run.conversation_id is not None:
        await enqueue_task(
            db,
            workspace_id=workspace_id,
            project_id=run.project_id,
            kind="agent_run",
            payload={"run_id": str(run.id), "conversation_id": str(run.conversation_id)},
        )
    await db.commit()
    await db.refresh(run)
    return run
