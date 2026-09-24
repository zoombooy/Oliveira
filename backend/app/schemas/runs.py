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


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectOut(BaseModel):
    id: UUID
    name: str
    description: str
    owner_id: UUID
    created_at: datetime
