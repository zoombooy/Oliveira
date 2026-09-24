from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class EvaluationCaseCreate(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    expected_chunk_ids: list[str] = Field(default_factory=list, max_length=50)
    expected_document_ids: list[str] = Field(default_factory=list, max_length=50)
    reference_answer: str = Field(default="", max_length=20000)
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reference(self):
        if not self.expected_chunk_ids and not self.expected_document_ids:
            raise ValueError("评估用例至少需要一个 expected_chunk_id 或 expected_document_id")
        return self


class EvaluationCaseOut(BaseModel):
    id: UUID
    project_id: UUID
    question: str
    expected_chunk_ids: list[str]
    expected_document_ids: list[str]
    reference_answer: str
    metadata: dict
    active: bool
    created_at: datetime


class EvaluationRunCreate(BaseModel):
    case_ids: list[UUID] | None = None
    top_k: int = Field(default=8, ge=1, le=50)
    version_id: UUID | None = None


class EvaluationRunOut(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    config: dict
    metrics: dict
    total_cases: int
    completed_cases: int
    error: str | None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class EvaluationResultOut(BaseModel):
    id: UUID
    run_id: UUID
    case_id: UUID
    retrieved_chunk_ids: list[str]
    first_hit_rank: int | None
    hit_at_k: bool
    reciprocal_rank: float
    error: str | None
    created_at: datetime
