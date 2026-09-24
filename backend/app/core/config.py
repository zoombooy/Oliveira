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

    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_top_k: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
