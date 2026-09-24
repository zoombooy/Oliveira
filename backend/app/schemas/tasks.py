from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TaskOut(BaseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID | None
    kind: str
    status: str
    payload: dict
    result: dict
    attempts: int
    max_attempts: int
    available_at: datetime
    last_error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
