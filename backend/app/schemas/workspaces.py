from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    owner_id: UUID
    created_at: datetime


class WorkspaceMemberCreate(BaseModel):
    username: str = Field(min_length=3, max_length=320)
    role: str = Field(default="member", pattern="^(admin|member|viewer)$")


class WorkspaceMemberOut(BaseModel):
    workspace_id: UUID
    user_id: UUID
    username: str
    role: str


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider_type: str = Field(default="openai_compatible", pattern="^(openai_compatible|ollama|vllm)$")
    base_url: str = Field(min_length=1, max_length=500)
    chat_model: str = Field(min_length=1, max_length=200)
    embedding_model: str = Field(default="", max_length=200)
    api_key: str = Field(default="", max_length=1000)
    is_default: bool = False


class ProviderOut(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    provider_type: str
    base_url: str
    chat_model: str
    embedding_model: str
    has_api_key: bool
    capabilities: dict
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ProviderPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    provider_type: str | None = Field(
        default=None, pattern="^(openai_compatible|ollama|vllm)$"
    )
    base_url: str | None = Field(default=None, max_length=500)
    chat_model: str | None = Field(default=None, max_length=200)
    embedding_model: str | None = Field(default=None, max_length=200)
    api_key: str | None = Field(default=None, max_length=1000)
    is_default: bool | None = None
