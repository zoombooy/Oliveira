from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_workspace_member
from app.core.database import get_session
from app.core.security import decrypt_secret, encrypt_secret
from app.models.tables import Project, ProviderProfile, User, Workspace, WorkspaceMember
from app.schemas.workspaces import (
    ProviderCreate,
    ProviderOut,
    ProviderPatch,
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberOut,
    WorkspaceOut,
)

router = APIRouter(prefix="/api/v1", tags=["workspaces"])


def _provider_out(item: ProviderProfile) -> ProviderOut:
    return ProviderOut(
        id=item.id,
        workspace_id=item.workspace_id,
        name=item.name,
        provider_type=item.provider_type,
        base_url=item.base_url,
        chat_model=item.chat_model,
        embedding_model=item.embedding_model,
        has_api_key=bool(item.api_key_ciphertext),
        capabilities=item.capabilities or {},
        is_default=item.is_default,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Workspace:
    workspace = Workspace(name=body.name.strip(), owner_id=user.id)
    db.add(workspace)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    await db.commit()
    await db.refresh(workspace)
    return workspace


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> list[Workspace]:
    stmt = (
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.created_at)
    )
    return list((await db.execute(stmt)).scalars())


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(
    workspace_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Workspace:
    await require_workspace_member(workspace_id, user, db)
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作空间不存在")
    return workspace


@router.post("/workspaces/{workspace_id}/members", response_model=WorkspaceMemberOut, status_code=201)
async def add_member(
    workspace_id: UUID,
    body: WorkspaceMemberCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> WorkspaceMemberOut:
    await require_workspace_member(workspace_id, user, db, roles={"owner", "admin"})
    target = (await db.execute(select(User).where(User.username == body.username.lower()))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="目标用户不存在")
    member = WorkspaceMember(workspace_id=workspace_id, user_id=target.id, role=body.role)
    db.add(member)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="用户已经是工作空间成员") from exc
    return WorkspaceMemberOut(
        workspace_id=workspace_id,
        user_id=target.id,
        username=target.username,
        role=member.role,
    )


@router.post("/workspaces/{workspace_id}/providers", response_model=ProviderOut, status_code=201)
async def create_provider(
    workspace_id: UUID,
    body: ProviderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ProviderOut:
    await require_workspace_member(workspace_id, user, db, roles={"owner", "admin"})
    if body.is_default:
        await db.execute(
            ProviderProfile.__table__.update()
            .where(ProviderProfile.workspace_id == workspace_id)
            .values(is_default=False)
        )
    item = ProviderProfile(
        workspace_id=workspace_id,
        name=body.name.strip(),
        provider_type=body.provider_type,
        base_url=body.base_url.rstrip("/"),
        chat_model=body.chat_model,
        embedding_model=body.embedding_model,
        api_key_ciphertext=encrypt_secret(body.api_key),
        is_default=body.is_default,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _provider_out(item)


@router.get("/workspaces/{workspace_id}/providers", response_model=list[ProviderOut])
async def list_providers(
    workspace_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[ProviderOut]:
    await require_workspace_member(workspace_id, user, db)
    items = list(
        (
            await db.execute(
                select(ProviderProfile)
                .where(ProviderProfile.workspace_id == workspace_id)
                .order_by(ProviderProfile.created_at)
            )
        ).scalars()
    )
    return [_provider_out(item) for item in items]


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
async def patch_provider(
    provider_id: UUID,
    body: ProviderPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ProviderOut:
    item = await db.get(ProviderProfile, provider_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    await require_workspace_member(item.workspace_id, user, db, roles={"owner", "admin"})
    for name in (
        "name",
        "provider_type",
        "base_url",
        "chat_model",
        "embedding_model",
        "is_default",
    ):
        value = getattr(body, name)
        if value is not None:
            setattr(item, name, value.rstrip("/") if name == "base_url" else value)
    if body.api_key is not None:
        item.api_key_ciphertext = encrypt_secret(body.api_key)
    if body.is_default:
        await db.execute(
            ProviderProfile.__table__.update()
            .where(
                ProviderProfile.workspace_id == item.workspace_id,
                ProviderProfile.id != item.id,
            )
            .values(is_default=False)
        )
    await db.commit()
    await db.refresh(item)
    return _provider_out(item)


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> None:
    item = await db.get(ProviderProfile, provider_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    await require_workspace_member(item.workspace_id, user, db, roles={"owner", "admin"})
    in_use = (
        await db.execute(
            select(Project.id)
            .where(Project.provider_id == item.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if in_use is not None:
        raise HTTPException(status_code=409, detail="该供应商仍被项目使用，请先切换项目供应商")
    await db.delete(item)
    await db.commit()


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    item = await db.get(ProviderProfile, provider_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    await require_workspace_member(item.workspace_id, user, db)
    headers = {}
    api_key = decrypt_secret(item.api_key_ciphertext)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{item.base_url}/models", headers=headers)
            response.raise_for_status()
        return {"ok": True, "status_code": response.status_code, "provider_id": str(item.id)}
    except Exception as exc:
        return {"ok": False, "provider_id": str(item.id), "error": str(exc)[:500]}
