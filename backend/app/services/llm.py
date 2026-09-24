"""OpenAI 兼容端点适配器（chat + embeddings）。"""

import httpx

from app.core.config import Settings, get_settings


class LLMNotConfigured(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model
        self.embedding_model = settings.embedding_model

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    @property
    def embedding_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.embedding_model)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

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
