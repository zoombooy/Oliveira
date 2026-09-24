from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class FactOut(BaseModel):
    id: UUID
    project_id: UUID
    subject_text: str
    predicate: str
    object_text: str
    status: str
    confidence: float | None
    valid_from: datetime | None
    valid_to: datetime | None
    recorded_at: datetime | None
    evidence_ref_id: UUID | None
    created_at: datetime


class ReviewItemOut(BaseModel):
    id: UUID
    project_id: UUID
    item_type: str
    ref_id: UUID
    reason: str
    status: str
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None
    resolution: str


class ResolveReviewIn(BaseModel):
    resolution: str = Field(default="", max_length=4000)


class ExtractFactsIn(BaseModel):
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)
