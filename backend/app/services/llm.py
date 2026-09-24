"""OpenAI 兼容端点适配器（chat + embeddings）。"""

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import decrypt_secret
from app.models.tables import Project, ProviderProfile


class LLMNotConfigured(RuntimeError):
    pass


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        embedding_model: str | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.llm_base_url).rstrip("/")
        self.api_key = settings.llm_api_key if api_key is None else api_key
        self.model = settings.llm_model if model is None else model
        self.embedding_model = settings.embedding_model if embedding_model is None else embedding_model

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    @property
    def embedding_configured(self) -> bool:
        return bool(self.base_url and self.embedding_model)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def chat(self, messages: list[dict], *, temperature: float = 0.2) -> str:
        if not self.configured:
            raise LLMNotConfigured("LLM 未配置：请设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL")
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={"model": self.model, "messages": messages, "temperature": temperature},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        """未配置嵌入模型时返回 None，调用方降级为关键词检索。"""
        if not texts or not self.embedding_configured:
            return None
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                headers=self._headers(),
                json={"model": self.embedding_model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            return [item["embedding"] for item in data]


def get_llm() -> LLMClient:
    return LLMClient(get_settings())


async def get_llm_for_scope(
    db: AsyncSession,
    workspace_id,
    project_id=None,
) -> LLMClient:
    """Resolve a project provider or the workspace default provider."""
    settings = get_settings()
    provider = None
    if project_id is not None:
        project = await db.get(Project, project_id)
        if project is not None and project.workspace_id == workspace_id:
            provider = await db.get(ProviderProfile, project.provider_id) if project.provider_id else None
            if provider is not None and provider.workspace_id != workspace_id:
                provider = None
    if provider is None:
        provider = (
            await db.execute(
                select(ProviderProfile)
                .where(
                    ProviderProfile.workspace_id == workspace_id,
                    ProviderProfile.is_default.is_(True),
                )
                .order_by(ProviderProfile.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
    if provider is None:
        return get_llm()
    api_key = decrypt_secret(provider.api_key_ciphertext) if provider.api_key_ciphertext else ""
    return LLMClient(
        settings,
        base_url=provider.base_url,
        api_key=api_key,
        model=provider.chat_model,
        embedding_model=provider.embedding_model,
    )


async def get_llm_for_project(db: AsyncSession, project_id) -> LLMClient:
    """Backward-compatible project provider resolver for pipelines."""
    project = await db.get(Project, project_id)
    if project is None:
        return get_llm()
    return await get_llm_for_scope(db, project.workspace_id, project.id)
