from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: UUID
    title: str
    version_no: int
    parse_status: str
    index_status: str
    chunk_count: int
    embedded: bool
    created_at: datetime


class DocumentDetailOut(DocumentOut):
    project_id: UUID
    file_name: str
    size_bytes: int
    content_hash: str
    object_key: str


class DocumentVersionOut(BaseModel):
    id: UUID
    document_id: UUID
    version_no: int
    file_name: str
    mime_type: str
    size_bytes: int
    content_hash: str
    parse_status: str
    index_status: str
    object_key: str
    created_at: datetime
