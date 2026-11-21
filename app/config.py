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
    log_level: str = "INFO"
    log_format: str = "text"
    database_url: str = "sqlite+aiosqlite:///./ai_power.db"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_seconds: int = 30
    jwt_secret: str = "dev-only-insecure-secret-change-me-0123456789"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 7
    password_min_length: int = 8
    redis_url: str = "redis://localhost:6379/0"
    login_rate_limit_per_minute: int = 10
    quota_free_requests_per_minute: int = 60
    quota_free_tokens_per_day: int = 200_000
    quota_free_max_keys: int = 5
    quota_pro_requests_per_minute: int = 600
    quota_pro_tokens_per_day: int = 5_000_000
    quota_pro_max_keys: int = 50
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

    agent_max_steps: int = 8
    agent_tool_timeout_seconds: float = 10.0
    agent_tool_output_max_chars: int = 4000
    audit_log_retention_days: int = 90
    workflow_node_timeout_seconds: float = 120.0
    workflow_node_attempts: int = 2
    workflow_max_nodes: int = 20

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
    def _validate_agent_settings(self) -> "Settings":
        if self.agent_max_steps < 1:
            raise ValueError("AGENT_MAX_STEPS must be >= 1")
        if self.agent_tool_timeout_seconds <= 0:
            raise ValueError("AGENT_TOOL_TIMEOUT_SECONDS must be > 0")
        if self.agent_tool_output_max_chars < 1:
            raise ValueError("AGENT_TOOL_OUTPUT_MAX_CHARS must be >= 1")
        if self.audit_log_retention_days < 1:
            raise ValueError("AUDIT_LOG_RETENTION_DAYS must be >= 1")
        if self.workflow_node_timeout_seconds <= 0:
            raise ValueError("WORKFLOW_NODE_TIMEOUT_SECONDS must be > 0")
        if self.workflow_node_attempts < 1:
            raise ValueError("WORKFLOW_NODE_ATTEMPTS must be >= 1")
        if self.workflow_max_nodes < 1:
            raise ValueError("WORKFLOW_MAX_NODES must be >= 1")
        return self

    @model_validator(mode="after")
    def _validate_db_pool_settings(self) -> "Settings":
        if self.db_pool_size < 1:
            raise ValueError("DB_POOL_SIZE must be >= 1")
        if self.db_max_overflow < 0:
            raise ValueError("DB_MAX_OVERFLOW must be >= 0")
        if self.db_pool_timeout_seconds < 1:
            raise ValueError("DB_POOL_TIMEOUT_SECONDS must be >= 1")
        return self

    @model_validator(mode="after")
    def _validate_quota_settings(self) -> "Settings":
        for name in (
            "quota_free_requests_per_minute",
            "quota_free_tokens_per_day",
            "quota_free_max_keys",
            "quota_pro_requests_per_minute",
            "quota_pro_tokens_per_day",
            "quota_pro_max_keys",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name.upper()} must be >= 1")
        return self

    @model_validator(mode="after")
    def _validate_logging_settings(self) -> "Settings":
        if self.log_format not in {"text", "json"}:
            raise ValueError("LOG_FORMAT must be 'text' or 'json'")
        if self.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be a standard Python log level")
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
