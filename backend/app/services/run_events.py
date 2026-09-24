from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import RunEvent


async def append_run_event(
    db: AsyncSession, run_id: UUID, event_type: str, payload: dict | None = None
) -> RunEvent:
    next_seq = (
        await db.execute(
            select(func.coalesce(func.max(RunEvent.seq), 0) + 1).where(RunEvent.run_id == run_id)
        )
    ).scalar_one()
    event = RunEvent(
        run_id=run_id,
        seq=int(next_seq),
        event_type=event_type,
        payload=payload or {},
    )
    db.add(event)
    await db.flush()
    return event
