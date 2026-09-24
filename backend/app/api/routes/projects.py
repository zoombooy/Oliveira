from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_workspace_member
from app.core.database import get_session
from app.models.tables import Project, ProviderProfile, User, Workspace, WorkspaceMember
from app.schemas.runs import ProjectCreate, ProjectOut

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Project:
    workspace_id = body.workspace_id
    if workspace_id is None:
        workspace_id = (
            await db.execute(
                select(Workspace.id)
                .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                .where(WorkspaceMember.user_id == user.id)
                .order_by(Workspace.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
    if workspace_id is None:
        raise HTTPException(status_code=400, detail="请先创建工作空间")
    await require_workspace_member(workspace_id, user, db, roles={"owner", "admin", "member"})
    if body.provider_id is not None:
        provider = await db.get(ProviderProfile, body.provider_id)
        if provider is None or provider.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail="Provider 不属于该工作空间")
    project = Project(
        workspace_id=workspace_id,
        name=body.name,
        description=body.description,
        owner_id=user.id,
        provider_id=body.provider_id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    workspace_id: UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[Project]:
    if workspace_id is not None:
        await require_workspace_member(workspace_id, user, db)
        stmt = select(Project).where(Project.workspace_id == workspace_id)
    else:
        stmt = (
            select(Project)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Project.workspace_id)
            .where(WorkspaceMember.user_id == user.id)
        )
    return list((await db.execute(stmt.order_by(Project.created_at))).scalars())
