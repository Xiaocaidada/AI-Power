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
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 7
    password_min_length: int = 8
    redis_url: str = "redis://localhost:6379/0"
    login_rate_limit_per_minute: int = 10
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://192.168.29.100:8080"

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
    ingestion_max_attempts: int = 3
    ingestion_lease_minutes: int = 15

    retrieval_top_k: int = 5
    retrieval_max_context_chars: int = 6000

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

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
        if self.ingestion_max_attempts < 1:
            raise ValueError("INGESTION_MAX_ATTEMPTS must be >= 1")
        if self.ingestion_lease_minutes < 1:
            raise ValueError("INGESTION_LEASE_MINUTES must be >= 1")
        return self

    @model_validator(mode="after")
    def _validate_retrieval_settings(self) -> "Settings":
        if self.retrieval_top_k < 1:
            raise ValueError("RETRIEVAL_TOP_K must be >= 1")
        if self.retrieval_max_context_chars < 1:
            raise ValueError("RETRIEVAL_MAX_CONTEXT_CHARS must be >= 1")
        return self

    @model_validator(mode="after")
    def _validate_auth_settings(self) -> "Settings":
        if self.access_token_ttl_minutes < 1:
            raise ValueError("ACCESS_TOKEN_TTL_MINUTES must be >= 1")
        if self.refresh_token_ttl_days < 1:
            raise ValueError("REFRESH_TOKEN_TTL_DAYS must be >= 1")
        if self.login_rate_limit_per_minute < 1:
            raise ValueError("LOGIN_RATE_LIMIT_PER_MINUTE must be >= 1")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
