from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str = "新对话"


class ConversationOut(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    created_at: datetime


class MessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    run_id: UUID | None = None
    created_at: datetime


class AskIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class CitationOut(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    page_number: int | None
    score: float
    method: str
    snippet: str


class AskOut(BaseModel):
    conversation_id: UUID
    message: MessageOut
    citations: list[CitationOut]
    run_id: UUID


class AskAcceptedOut(BaseModel):
    run_id: UUID
    user_message_id: UUID
    status: str
