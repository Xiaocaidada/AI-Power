from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    database_url: str = "sqlite+aiosqlite:///./ai_power.db"
    jwt_secret: str = "dev-only-insecure-secret-change-me-0123456789"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 1440
    password_min_length: int = 8

    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    local_llm_base_url: str = "http://192.168.29.100:8083/v1"
    local_llm_api_key: str = ""
    local_llm_model: str = (
        "/home/wq/models/qwen2.5-7b-instruct/qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf"
    )
    provider_timeout_seconds: float = 60.0

    upload_dir: str = "./uploads"
    max_upload_bytes: int = 20 * 1024 * 1024
    max_document_pages: int = 200
    chunk_max_chars: int = 1000
    chunk_overlap_chars: int = 150
    embedding_base_url: str = "http://192.168.29.100:8000/v1"
    embedding_api_key: str = ""
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    embedding_batch_size: int = 16

    @model_validator(mode="after")
    def _forbid_dev_secret_outside_dev(self) -> "Settings":
        if self.app_env != "dev" and self.jwt_secret.startswith("dev-"):
            raise ValueError("JWT_SECRET must be set to a generated value outside dev")
        return self

    @model_validator(mode="after")
    def _validate_ingestion_settings(self) -> "Settings":
        if self.chunk_overlap_chars >= self.chunk_max_chars:
            raise ValueError("CHUNK_OVERLAP_CHARS must be smaller than CHUNK_MAX_CHARS")
        if self.embedding_batch_size < 1:
            raise ValueError("EMBEDDING_BATCH_SIZE must be >= 1")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
