from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RunOut(BaseModel):
    id: UUID
    project_id: UUID
    conversation_id: UUID | None
    kind: str
    agent_key: str
    status: str
    input: dict
    output: dict
    error: str | None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunEventOut(BaseModel):
    id: UUID
    run_id: UUID
    seq: int
    event_type: str
    payload: dict
    occurred_at: datetime


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    workspace_id: UUID | None = None
    provider_id: UUID | None = None


class ProjectOut(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    description: str
    owner_id: UUID
    provider_id: UUID | None
    created_at: datetime


class ProjectPatch(BaseModel):
    provider_id: UUID | None = None
