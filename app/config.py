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
    quota_free_daily_cost_usd: float = 1.0
    quota_pro_daily_cost_usd: float = 50.0
    quota_free_max_kbs: int = 10
    quota_pro_max_kbs: int = 100
    quota_free_max_documents_per_kb: int = 200
    quota_pro_max_documents_per_kb: int = 5000
    quota_free_max_kb_bytes: int = 100_000_000
    quota_pro_max_kb_bytes: int = 10_000_000_000
    quota_free_max_memories: int = 500
    quota_pro_max_memories: int = 10_000
    budget_webhook_url: str = ""
    webhook_secret_key: str = ""
    provider_secret_key: str = ""
    webhook_allow_private_hosts: bool = False
    webhook_timeout_seconds: float = 10.0
    webhook_max_attempts: int = 5
    plugin_allowed_hosts: str = ""
    plugin_allow_private_hosts: bool = False
    plugin_timeout_seconds: float = 10.0
    plugin_max_response_chars: int = 8000
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

    inner_models_dir: str = "inner_models"
    inner_models_providers: str = "*"
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
    retrieval_candidate_k: int = 20
    retrieval_hybrid_enabled: bool = True
    retrieval_max_context_chars: int = 6000
    rerank_enabled: bool = True
    rerank_base_url: str = "http://192.168.29.100:8001/v1"
    rerank_api_key: str = ""
    rerank_model: str = "bge-reranker-v2-m3"
    rerank_timeout_seconds: float = 10.0
    rerank_max_candidates: int = 8
    rerank_max_doc_chars: int = 800

    agent_max_steps: int = 8
    agent_tool_timeout_seconds: float = 10.0
    agent_tool_output_max_chars: int = 4000
    research_max_steps: int = 6
    research_step_source_limit: int = 5
    research_max_sources: int = 30
    research_max_llm_calls: int = 10
    research_max_total_tokens: int = 150_000
    agent_task_max_steps: int = 10
    agent_task_max_tool_calls: int = 15
    agent_task_max_total_tokens: int = 150_000
    integration_image_timeout_seconds: float = 120.0
    integration_max_image_bytes: int = 10_000_000
    integration_max_images_per_request: int = 4
    integration_max_prompt_chars: int = 4000
    integration_audio_timeout_seconds: float = 90.0
    integration_max_audio_bytes: int = 20_000_000
    integration_tts_max_chars: int = 4000
    integration_media_retention_days: int = 30
    integration_github_timeout_seconds: float = 20.0
    skill_run_max_steps: int = 8
    audit_log_retention_days: int = 90
    workflow_node_timeout_seconds: float = 120.0
    workflow_node_attempts: int = 2
    workflow_max_nodes: int = 20
    workflow_parallel_limit: int = 3
    workflow_review_timeout_seconds: float = 3600.0
    workflow_review_poll_seconds: float = 0.5
    workflow_loop_max_iterations: int = 20
    http_node_timeout_seconds: float = 15.0
    http_node_max_response_chars: int = 8000
    http_node_allowed_hosts: str = ""
    http_node_allow_private_hosts: bool = False
    url_import_enabled: bool = True
    url_import_timeout_seconds: float = 20.0
    url_import_max_bytes: int = 5_000_000
    url_import_allowed_hosts: str = ""
    url_import_allow_private_hosts: bool = False
    url_import_max_redirects: int = 3
    url_import_crawl_max_pages: int = 20
    ocr_enabled: bool = False
    ocr_base_url: str = ""
    ocr_api_key: str = ""
    ocr_model: str = ""
    ocr_timeout_seconds: float = 60.0
    ocr_max_image_bytes: int = 10_000_000
    ocr_max_output_chars: int = 20000
    ocr_prompt: str = (
        "Extract all readable text from this image. "
        "Preserve line breaks and tables as plain text. Return text only."
    )
    mcp_timeout_seconds: float = 20.0
    mcp_max_response_chars: int = 8000
    agent_memory_inject_limit: int = 5
    agent_memory_inject_chars: int = 2000
    memory_embedding_enabled: bool = True
    memory_embedding_timeout_seconds: float = 10.0
    memory_extraction_enabled: bool = True
    memory_extraction_provider_id: str = ""
    memory_extraction_model: str = ""
    memory_extraction_max_chars: int = 6000
    memory_extraction_max_candidates: int = 5
    memory_extraction_min_confidence: float = 0.5
    code_node_max_output_chars: int = 20000
    database_node_max_rows: int = 100
    database_node_timeout_seconds: float = 15.0
    collaboration_max_tasks: int = 4
    collaboration_max_rounds: int = 2
    collaboration_max_steps: int = 16
    collaboration_parallel_limit: int = 3
    collaboration_task_timeout_seconds: float = 180.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def _forbid_dev_secret_outside_dev(self) -> "Settings":
        if self.app_env != "dev" and self.jwt_secret.startswith("dev-"):
            raise ValueError("JWT_SECRET must be set to a generated value outside dev")
        if self.app_env != "dev" and not self.webhook_secret_key.strip():
            raise ValueError("WEBHOOK_SECRET_KEY must be set outside dev")
        if self.app_env != "dev" and not self.provider_secret_key.strip():
            raise ValueError("PROVIDER_SECRET_KEY must be set outside dev")
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
        if self.retrieval_candidate_k < self.retrieval_top_k:
            raise ValueError("RETRIEVAL_CANDIDATE_K must be >= RETRIEVAL_TOP_K")
        if self.retrieval_max_context_chars < 1:
            raise ValueError("RETRIEVAL_MAX_CONTEXT_CHARS must be >= 1")
        if self.rerank_timeout_seconds <= 0:
            raise ValueError("RERANK_TIMEOUT_SECONDS must be > 0")
        if self.rerank_max_candidates < 1:
            raise ValueError("RERANK_MAX_CANDIDATES must be >= 1")
        if self.rerank_max_doc_chars < 1:
            raise ValueError("RERANK_MAX_DOC_CHARS must be >= 1")
        if self.rerank_enabled and not self.rerank_base_url.strip():
            raise ValueError("RERANK_BASE_URL is required when RERANK_ENABLED is true")
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
        if self.webhook_timeout_seconds <= 0:
            raise ValueError("WEBHOOK_TIMEOUT_SECONDS must be > 0")
        if self.webhook_max_attempts < 1:
            raise ValueError("WEBHOOK_MAX_ATTEMPTS must be >= 1")
        if self.plugin_timeout_seconds <= 0:
            raise ValueError("PLUGIN_TIMEOUT_SECONDS must be > 0")
        if self.plugin_max_response_chars < 1:
            raise ValueError("PLUGIN_MAX_RESPONSE_CHARS must be >= 1")
        if self.workflow_node_timeout_seconds <= 0:
            raise ValueError("WORKFLOW_NODE_TIMEOUT_SECONDS must be > 0")
        if self.workflow_node_attempts < 1:
            raise ValueError("WORKFLOW_NODE_ATTEMPTS must be >= 1")
        if self.workflow_max_nodes < 1:
            raise ValueError("WORKFLOW_MAX_NODES must be >= 1")
        if self.workflow_parallel_limit < 1:
            raise ValueError("WORKFLOW_PARALLEL_LIMIT must be >= 1")
        if self.workflow_review_timeout_seconds <= 0:
            raise ValueError("WORKFLOW_REVIEW_TIMEOUT_SECONDS must be > 0")
        if self.workflow_review_poll_seconds <= 0:
            raise ValueError("WORKFLOW_REVIEW_POLL_SECONDS must be > 0")
        if self.workflow_loop_max_iterations < 1:
            raise ValueError("WORKFLOW_LOOP_MAX_ITERATIONS must be >= 1")
        if self.http_node_timeout_seconds <= 0:
            raise ValueError("HTTP_NODE_TIMEOUT_SECONDS must be > 0")
        if self.http_node_max_response_chars < 1:
            raise ValueError("HTTP_NODE_MAX_RESPONSE_CHARS must be >= 1")
        if self.url_import_timeout_seconds <= 0:
            raise ValueError("URL_IMPORT_TIMEOUT_SECONDS must be > 0")
        if self.url_import_max_bytes < 1:
            raise ValueError("URL_IMPORT_MAX_BYTES must be >= 1")
        if self.url_import_max_redirects < 0:
            raise ValueError("URL_IMPORT_MAX_REDIRECTS must be >= 0")
        if self.url_import_crawl_max_pages < 1:
            raise ValueError("URL_IMPORT_CRAWL_MAX_PAGES must be >= 1")
        if self.ocr_timeout_seconds <= 0:
            raise ValueError("OCR_TIMEOUT_SECONDS must be > 0")
        if self.ocr_max_image_bytes < 1:
            raise ValueError("OCR_MAX_IMAGE_BYTES must be >= 1")
        if self.ocr_enabled and (
            not self.ocr_base_url.strip() or not self.ocr_model.strip()
        ):
            raise ValueError("OCR_ENABLED requires OCR_BASE_URL and OCR_MODEL")
        if self.mcp_timeout_seconds <= 0:
            raise ValueError("MCP_TIMEOUT_SECONDS must be > 0")
        if self.mcp_max_response_chars < 1:
            raise ValueError("MCP_MAX_RESPONSE_CHARS must be >= 1")
        if self.agent_memory_inject_limit < 1:
            raise ValueError("AGENT_MEMORY_INJECT_LIMIT must be >= 1")
        if self.agent_memory_inject_chars < 1:
            raise ValueError("AGENT_MEMORY_INJECT_CHARS must be >= 1")
        if self.code_node_max_output_chars < 1:
            raise ValueError("CODE_NODE_MAX_OUTPUT_CHARS must be >= 1")
        if self.database_node_max_rows < 1:
            raise ValueError("DATABASE_NODE_MAX_ROWS must be >= 1")
        if self.database_node_timeout_seconds <= 0:
            raise ValueError("DATABASE_NODE_TIMEOUT_SECONDS must be > 0")
        if self.memory_embedding_timeout_seconds <= 0:
            raise ValueError("MEMORY_EMBEDDING_TIMEOUT_SECONDS must be > 0")
        if self.collaboration_max_tasks < 2:
            raise ValueError("COLLABORATION_MAX_TASKS must be >= 2")
        if self.collaboration_max_rounds < 1:
            raise ValueError("COLLABORATION_MAX_ROUNDS must be >= 1")
        if self.collaboration_max_steps < 1:
            raise ValueError("COLLABORATION_MAX_STEPS must be >= 1")
        if self.collaboration_parallel_limit < 1:
            raise ValueError("COLLABORATION_PARALLEL_LIMIT must be >= 1")
        if self.collaboration_task_timeout_seconds <= 0:
            raise ValueError("COLLABORATION_TASK_TIMEOUT_SECONDS must be > 0")
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
            "quota_free_max_kbs",
            "quota_pro_max_kbs",
            "quota_free_max_documents_per_kb",
            "quota_pro_max_documents_per_kb",
            "quota_free_max_kb_bytes",
            "quota_pro_max_kb_bytes",
            "quota_free_max_memories",
            "quota_pro_max_memories",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name.upper()} must be >= 1")
        for name in ("quota_free_daily_cost_usd", "quota_pro_daily_cost_usd"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name.upper()} must be > 0")
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
