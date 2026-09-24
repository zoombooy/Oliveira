from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import decode_access_token
from app.models.tables import Project, User, WorkspaceMember

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_session),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录状态无效或已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = UUID(decode_access_token(token))
    except (ValueError, jwt.InvalidTokenError) as exc:
        raise credentials_error from exc
    user = await db.get(User, user_id)
    if user is None:
        raise credentials_error
    return user


async def require_workspace_member(
    workspace_id: UUID,
    user: User,
    db: AsyncSession,
    *,
    roles: set[str] | None = None,
) -> WorkspaceMember:
    member = (
        await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if member is None or (roles is not None and member.role not in roles):
        raise HTTPException(status_code=403, detail="无权访问该工作空间")
    return member


async def require_project_access(
    project_id: UUID,
    user: User,
    db: AsyncSession,
    *,
    roles: set[str] | None = None,
) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    await require_workspace_member(project.workspace_id, user, db, roles=roles)
    return project
