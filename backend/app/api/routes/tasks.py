from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_project_access, require_workspace_member
from app.core.database import get_session
from app.models.tables import Task, User
from app.schemas.tasks import TaskOut

router = APIRouter(prefix="/api/v1", tags=["tasks"])


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.project_id is not None:
        await require_project_access(task.project_id, user, db)
    else:
        await require_workspace_member(task.workspace_id, user, db)
    return task
