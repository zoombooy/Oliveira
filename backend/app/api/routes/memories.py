from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_session
from app.models.tables import User, UserMemory
from app.schemas.memories import MemoryCreate, MemoryOut, MemoryPatch

router = APIRouter(prefix="/api/v1/users/me/memories", tags=["memories"])


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> list[UserMemory]:
    return list(
        (
            await db.execute(
                select(UserMemory)
                .where(UserMemory.user_id == user.id)
                .order_by(UserMemory.status, UserMemory.updated_at.desc())
            )
        ).scalars()
    )


@router.post("", response_model=MemoryOut, status_code=201)
async def create_memory(
    body: MemoryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> UserMemory:
    memory = UserMemory(
        user_id=user.id,
        key=body.key.strip(),
        value=body.value.strip(),
        source_message_id=body.source_message_id,
        source_run_id=body.source_run_id,
        confidence=1.0,
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return memory


@router.patch("/{memory_id}", response_model=MemoryOut)
async def patch_memory(
    memory_id: UUID,
    body: MemoryPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> UserMemory:
    memory = await db.get(UserMemory, memory_id)
    if memory is None or memory.user_id != user.id:
        raise HTTPException(status_code=404, detail="记忆不存在")
    if body.value is not None:
        memory.value = body.value.strip()
    if body.status is not None:
        memory.status = body.status
        memory.retracted_at = datetime.now(timezone.utc) if body.status == "retracted" else None
    await db.commit()
    await db.refresh(memory)
    return memory


@router.delete("/{memory_id}", response_model=MemoryOut)
async def retract_memory(
    memory_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> UserMemory:
    memory = await db.get(UserMemory, memory_id)
    if memory is None or memory.user_id != user.id:
        raise HTTPException(status_code=404, detail="记忆不存在")
    memory.status = "retracted"
    memory.retracted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(memory)
    return memory
