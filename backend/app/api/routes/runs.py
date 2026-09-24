from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.tables import Run
from app.schemas.runs import RunOut

router = APIRouter(prefix="/api/v1", tags=["runs"])


@router.get("/runs", response_model=list[RunOut])
async def list_runs(project_id, db: AsyncSession = Depends(get_session)) -> list[Run]:
    stmt = select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc())
    return list((await db.execute(stmt)).scalars())


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id, db: AsyncSession = Depends(get_session)) -> Run:
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run 不存在")
    return run
