from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class MemoryCreate(BaseModel):
    key: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1, max_length=4000)
    source_message_id: UUID | None = None
    source_run_id: UUID | None = None


class MemoryPatch(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=4000)
    status: str | None = Field(default=None, pattern="^(active|retracted)$")


class MemoryOut(BaseModel):
    id: UUID
    user_id: UUID
    key: str
    value: str
    source_message_id: UUID | None
    source_run_id: UUID | None
    status: str
    confidence: float
    created_at: datetime
    updated_at: datetime
    retracted_at: datetime | None
