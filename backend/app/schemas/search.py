from uuid import UUID

from pydantic import BaseModel, Field


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    top_k: int = Field(default=8, ge=1, le=50)
    version_id: UUID | None = None


class SearchResultOut(BaseModel):
    chunk_id: str
    document_id: str
    document_version_id: str
    document_title: str
    page_number: int | None
    paragraph_index: int | None
    snippet: str
    vector_score: float | None
    keyword_score: float | None
    final_score: float
    methods: list[str]


class SearchOut(BaseModel):
    query: str
    results: list[SearchResultOut]
