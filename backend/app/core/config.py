from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Oliveira"

    database_url: str = "postgresql+asyncpg://oliveira:oliveira@localhost:5432/oliveira"
    data_dir: str = "./data"

    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    embedding_model: str = ""
    embedding_dim: int = 1024
    embedding_batch_size: int = 64

    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_top_k: int = 8
    vector_weight: float = 0.7
    keyword_weight: float = 0.3

    jwt_secret: str = "change-me-in-development"
    access_token_minutes: int = 60 * 24
    oliveira_master_key: str = ""
    app_env: str = "development"

    max_agent_steps: int = 6
    max_agent_runtime_seconds: int = 60
    max_tool_output_chars: int = 12000
    max_context_tokens: int = 12000
    task_poll_interval: float = 1.0
    worker_id: str = "local-worker"


@lru_cache
def get_settings() -> Settings:
    return Settings()
