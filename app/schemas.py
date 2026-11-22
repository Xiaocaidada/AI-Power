from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class ErrorOut(BaseModel):
    code: str
    message: str


class _NormalizedEmailModel(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class RegisterIn(_NormalizedEmailModel):
    password: str = Field(min_length=8, max_length=128)


class LoginIn(_NormalizedEmailModel):
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    role: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str
    refresh_expires_in: int


class RefreshTokenIn(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=512)


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class KnowledgeBaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_at: datetime


class ChunkingSettingsUpdate(BaseModel):
    chunk_size: int | None = Field(default=None, ge=50, le=4000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=1000)


class RetrievalSettingsUpdate(BaseModel):
    top_k: int | None = Field(default=None, ge=1, le=20)
    candidate_k: int | None = Field(default=None, ge=1, le=100)
    hybrid_enabled: bool | None = None
    rerank_enabled: bool | None = None


class EmbeddingSettingsUpdate(BaseModel):
    provider_config_id: UUID | None = None
    model: str | None = None
    dimensions: int | None = Field(default=None, ge=1, le=4096)


class RerankSettingsUpdate(BaseModel):
    provider_config_id: UUID | None = None
    model: str | None = None


class KnowledgeBaseSettingsUpdate(BaseModel):
    chunking: ChunkingSettingsUpdate | None = None
    retrieval: RetrievalSettingsUpdate | None = None
    embedding: EmbeddingSettingsUpdate | None = None
    rerank: RerankSettingsUpdate | None = None


class ChunkingSettingsOut(BaseModel):
    chunk_size: int
    chunk_overlap: int


class RetrievalSettingsOut(BaseModel):
    top_k: int
    candidate_k: int
    hybrid_enabled: bool
    rerank_enabled: bool


class EmbeddingSettingsOut(BaseModel):
    provider_config_id: UUID | None
    model: str | None
    dimensions: int


class RerankSettingsOut(BaseModel):
    provider_config_id: UUID | None
    model: str | None


class KnowledgeBaseSettingsOut(BaseModel):
    chunking: ChunkingSettingsOut
    retrieval: RetrievalSettingsOut
    embedding: EmbeddingSettingsOut
    rerank: RerankSettingsOut


class ChunkOut(BaseModel):
    id: UUID
    document_id: UUID
    filename: str
    chunk_index: int
    page_no: int | None
    text: str
    token_count: int | None
    char_count: int
    created_at: datetime


class ChunkPageOut(BaseModel):
    items: list[ChunkOut]
    total: int
    limit: int
    offset: int


class KnowledgeBaseStatsOut(BaseModel):
    document_count: int
    ready_count: int
    processing_count: int
    failed_count: int
    chunk_count: int
    char_count: int


class RetrievalSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int | None = Field(default=None, ge=1, le=20)
    candidate_k: int | None = Field(default=None, ge=1, le=100)
    hybrid_enabled: bool | None = None
    rerank_enabled: bool | None = None

    @field_validator("query", mode="before")
    @classmethod
    def strip_query(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class RetrievalHitOut(BaseModel):
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_no: int | None
    chunk_index: int
    text: str
    distance: float | None
    vector_rank: int | None
    lexical_rank: int | None
    fused_score: float | None
    rerank_score: float | None


class RetrievalTimingsOut(BaseModel):
    vector_ms: float
    lexical_ms: float
    rerank_ms: float
    total_ms: float


class RetrievalSearchOut(BaseModel):
    query: str
    mode: str
    hybrid_enabled: bool
    rerank_enabled: bool
    results: list[RetrievalHitOut]
    timings: RetrievalTimingsOut


class EvalQuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    relevant_document_ids: list[UUID] = Field(min_length=1, max_length=20)
    evidence: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("question", mode="before")
    @classmethod
    def strip_question(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class EvalDatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    questions: list[EvalQuestionIn] = Field(min_length=1, max_length=500)

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class EvalDatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    question_count: int
    created_at: datetime


class EvalQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    question: str
    relevant_document_ids: list[UUID]
    evidence: list[str]


class EvalDatasetDetailOut(EvalDatasetOut):
    questions: list[EvalQuestionOut]


class EvalBundleDocument(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    text: str = ""


class EvalBundleQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    relevant_filenames: list[str] = Field(min_length=1, max_length=20)
    evidence: list[str] = Field(default_factory=list, max_length=10)


class EvalBundle(BaseModel):
    description: str = Field(default="", max_length=500)
    documents: list[EvalBundleDocument] = Field(default_factory=list)
    questions: list[EvalBundleQuestion] = Field(min_length=1, max_length=500)


class EvalDatasetImportIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    kb_id: UUID
    bundle: EvalBundle

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class EvalRunCreate(BaseModel):
    dataset_id: UUID
    kb_id: UUID
    top_k: int | None = Field(default=None, ge=1, le=20)
    candidate_k: int | None = Field(default=None, ge=1, le=100)
    hybrid_enabled: bool | None = None
    rerank_enabled: bool | None = None
    answer_enabled: bool = False
    judge_enabled: bool = False
    provider_id: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=200)
    judge_provider_id: str | None = Field(default=None, max_length=50)
    judge_model: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _validate_judge(self) -> "EvalRunCreate":
        if self.judge_enabled and not self.answer_enabled:
            raise ValueError("judge_enabled requires answer_enabled")
        if self.answer_enabled and (not self.provider_id or not self.model):
            raise ValueError("answer_enabled requires provider_id and model")
        return self


class EvalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    kb_id: UUID
    status: str
    config: dict[str, object]
    metrics: dict[str, object] | None
    error_code: str | None
    progress_total: int
    progress_done: int
    prompt_tokens: int
    completion_tokens: int
    cost: float
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class EvalRunItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    question_id: UUID
    question_text: str
    hit_rank: int | None
    reciprocal_rank: float
    evidence_hit: bool | None
    latency_ms: float | None
    top_document_ids: list[str]
    top_chunk_ids: list[str]
    answer: str | None
    judge_score: int | None
    judge_faithful: bool | None
    judge_reason: str | None
    judge_error: str | None
    answer_latency_ms: float | None
    prompt_tokens: int
    completion_tokens: int
    cost: float
    error_code: str | None


class EvalRunDetailOut(EvalRunOut):
    items: list[EvalRunItemOut]


class EvalCompareOut(BaseModel):
    runs: list[EvalRunOut]


class WebhookCreate(BaseModel):
    url: str = Field(min_length=1, max_length=1000)
    events: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _validate_events(self) -> "WebhookCreate":
        from app.services.webhooks import WEBHOOK_EVENTS

        unknown = sorted(set(self.events) - WEBHOOK_EVENTS)
        if unknown:
            raise ValueError(f"unknown webhook events: {', '.join(unknown)}")
        return self

    @field_validator("url", mode="before")
    @classmethod
    def strip_url(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class WebhookUpdate(BaseModel):
    url: str | None = Field(default=None, min_length=1, max_length=1000)
    events: list[str] | None = Field(default=None, min_length=1, max_length=20)
    active: bool | None = None

    @model_validator(mode="after")
    def _validate_events(self) -> "WebhookUpdate":
        if self.events is None:
            return self
        from app.services.webhooks import WEBHOOK_EVENTS

        unknown = sorted(set(self.events) - WEBHOOK_EVENTS)
        if unknown:
            raise ValueError(f"unknown webhook events: {', '.join(unknown)}")
        return self

    @field_validator("url", mode="before")
    @classmethod
    def strip_url(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class WebhookOut(BaseModel):
    id: UUID
    url: str
    events: list[str]
    active: bool
    created_at: datetime


class WebhookCreatedOut(WebhookOut):
    secret: str


class WebhookDeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event: str
    status: str
    attempts: int
    response_status: int | None
    error: str | None
    next_attempt_at: datetime
    created_at: datetime
    delivered_at: datetime | None


class CollaborationRunCreate(BaseModel):
    input: str = Field(min_length=1, max_length=20000)
    provider_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=200)
    kb_id: UUID | None = None

    @field_validator("input", "provider_id", "model", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CollaborationStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    step_key: str
    status: str
    input_summary: str
    output_summary: str
    prompt_tokens: int
    completion_tokens: int
    cost: float
    error_code: str | None
    created_at: datetime


class CollaborationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: str
    model: str
    kb_id: UUID | None
    status: str
    input_text: str
    plan: list[dict[str, object]] | None
    final_output: str
    rounds: int
    error_code: str | None
    cancel_requested_at: datetime | None
    prompt_tokens: int
    completion_tokens: int
    cost: float
    total_ms: float | None
    started_at: datetime
    finished_at: datetime | None
    steps: list[CollaborationStepOut] = Field(default_factory=list)


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    definition: dict[str, object]

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class WorkflowVersionCreate(BaseModel):
    definition: dict[str, object]


class WorkflowVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    definition: dict[str, object]
    created_at: datetime


class WorkflowOut(BaseModel):
    id: UUID
    name: str
    description: str
    created_at: datetime
    versions: list[WorkflowVersionOut] = Field(default_factory=list)


class WorkflowRunCreate(BaseModel):
    version: int | None = None
    input: str = Field(min_length=1, max_length=20000)
    kb_id: UUID | None = None

    @field_validator("input", mode="before")
    @classmethod
    def strip_input(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class WorkflowNodeRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    node_id: str
    node_type: str
    status: str
    attempts: int
    input_summary: str
    output_summary: str
    error_code: str | None
    duration_ms: float | None
    created_at: datetime


class WorkflowRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID
    version_id: UUID
    kb_id: UUID | None
    status: str
    input_text: str
    error_code: str | None
    cancel_requested_at: datetime | None
    prompt_tokens: int
    completion_tokens: int
    cost: float
    total_ms: float | None
    started_at: datetime
    finished_at: datetime | None
    nodes: list[WorkflowNodeRunOut] = Field(default_factory=list)


class RunAcceptedOut(BaseModel):
    run_id: UUID
    status: str = "queued"


class RunCancelOut(BaseModel):
    run_id: UUID
    status: str
    cancel_requested_at: datetime | None


class PromptVersionCreate(BaseModel):
    system_prompt: str = Field(min_length=1, max_length=20000)

    @field_validator("system_prompt", mode="before")
    @classmethod
    def strip_prompt(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PromptTemplateCreate(PromptVersionCreate):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PromptRenderIn(BaseModel):
    version: int | None = None
    variables: dict[str, str] = Field(default_factory=dict)


class PromptVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    system_prompt: str
    variables: list[str]
    created_at: datetime


class PromptTemplateOut(BaseModel):
    id: UUID
    name: str
    description: str
    created_at: datetime
    versions: list[PromptVersionOut] = Field(default_factory=list)


class PromptRenderOut(BaseModel):
    rendered: str
    version: int
    variables: list[str]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=20000)
    default_provider_id: str | None = Field(default=None, max_length=50)
    default_model: str | None = Field(default=None, max_length=200)
    default_kb_id: UUID | None = None
    default_agent: bool = False

    @field_validator(
        "name", "description", "instructions", "default_provider_id", "default_model",
        mode="before",
    )
    @classmethod
    def strip_project_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    instructions: str | None = Field(default=None, max_length=20000)
    default_provider_id: str | None = Field(default=None, max_length=50)
    default_model: str | None = Field(default=None, max_length=200)
    default_kb_id: UUID | None = None
    default_agent: bool | None = None
    archived: bool | None = None

    @field_validator(
        "name", "description", "instructions", "default_provider_id", "default_model",
        mode="before",
    )
    @classmethod
    def strip_project_optional(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProjectOut(BaseModel):
    id: UUID
    name: str
    description: str
    instructions: str
    default_provider_id: str | None
    default_model: str | None
    default_kb_id: UUID | None
    default_agent: bool
    archived: bool
    conversation_count: int
    owned: bool
    created_at: datetime
    updated_at: datetime


class GenerationSettings(BaseModel):
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None


class ConversationCreate(BaseModel):
    provider_id: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=200)
    kb_id: UUID | None = None
    agent: bool = False
    project_id: UUID | None = None
    prompt_version_id: UUID | None = None
    prompt_variables: dict[str, str] = Field(default_factory=dict)

    @field_validator("provider_id", "model", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    provider_id: str
    model: str
    kb_id: UUID | None
    project_id: UUID | None = None
    agent: bool = False
    pinned: bool = False
    generation_settings: dict = Field(default_factory=dict)
    prompt_version_id: UUID | None = None
    created_at: datetime
    updated_at: datetime | None = None
    archived_at: datetime | None = None


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    pinned: bool | None = None
    project_id: UUID | None = None
    archived: bool | None = None
    provider_id: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=200)
    generation_settings: GenerationSettings | None = None

    @field_validator("title", "provider_id", "model", mode="before")
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ConversationBatchIn(BaseModel):
    action: Literal["archive", "unarchive", "move"]
    conversation_ids: list[UUID] = Field(min_length=1, max_length=100)
    project_id: UUID | None = None


class ConversationBatchOut(BaseModel):
    updated: int


class CitationOut(BaseModel):
    index: int
    document_id: UUID
    chunk_id: UUID
    page_no: int | None
    snippet: str


class MessageFeedbackOut(BaseModel):
    message_id: UUID
    rating: str
    reason: str
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    status: str
    provider_id: str | None
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    request_id: str | None = None
    reply_to_message_id: UUID | None = None
    created_at: datetime
    citations: list[CitationOut] = Field(default_factory=list)
    feedback: MessageFeedbackOut | None = None


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut] = Field(default_factory=list)


class MessageFeedbackIn(BaseModel):
    rating: Literal["up", "down"]
    reason: str = Field(default="", max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SendMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=20000)

    @field_validator("content", mode="before")
    @classmethod
    def strip_content(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProviderOut(BaseModel):
    id: str
    available: bool
    models: list[str] = Field(default_factory=list)


class ProviderConfigCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider_type: Literal["openai_compatible", "custom"] = "openai_compatible"
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str = Field(min_length=1, max_length=1000)
    note: str = Field(default="", max_length=500)
    shared: bool = False

    @field_validator("name", "base_url", "api_key", "note", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProviderConfigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    api_key: str | None = Field(default=None, max_length=1000)
    note: str | None = Field(default=None, max_length=500)
    shared: bool | None = None

    @field_validator("name", "base_url", "api_key", "note", mode="before")
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProviderConfigOut(BaseModel):
    id: UUID
    name: str
    provider_type: str
    base_url: str
    api_key_hint: str
    note: str
    shared: bool
    owned: bool
    status: str
    last_error: str | None
    last_tested_at: datetime | None
    model_count: int
    created_at: datetime
    updated_at: datetime


class ProviderModelCreate(BaseModel):
    model_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field(default="", max_length=200)
    capabilities: list[str] | None = None

    @field_validator("model_id", "display_name", mode="before")
    @classmethod
    def strip_model_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProviderModelUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    capabilities: list[str] | None = None
    enabled: bool | None = None


class ProviderModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    model_id: str
    display_name: str
    capabilities: list[str]
    source: str
    enabled: bool


class ProviderTestOut(BaseModel):
    status: str
    model_count: int
    error_code: str | None


class ProviderSyncOut(BaseModel):
    added: int
    updated: int
    total: int


class PersonalModelOut(BaseModel):
    provider_id: str
    provider_name: str
    model_id: str
    display_name: str
    capabilities: list[str]


class MarketModelCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=120)
    provider_id: str = Field(min_length=1, max_length=100)
    provider_name: str = Field(min_length=1, max_length=100)
    model_id: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    category: str = Field(default="general", max_length=50)
    capabilities: list[str] = Field(default_factory=lambda: ["chat", "stream"])
    input_types: list[str] = Field(default_factory=lambda: ["text"])
    output_types: list[str] = Field(default_factory=lambda: ["text"])
    context_window: int = Field(default=0, ge=0)
    max_output: int | None = Field(default=None, ge=0)
    logo_url: str = Field(default="", max_length=500)
    docs_url: str = Field(default="", max_length=500)
    featured: bool = False
    is_new: bool = False
    sort_order: int = 100
    enabled: bool = True


class MarketModelUpdate(BaseModel):
    slug: str | None = Field(
        default=None, min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    name: str | None = Field(default=None, min_length=1, max_length=120)
    provider_id: str | None = Field(default=None, min_length=1, max_length=100)
    provider_name: str | None = Field(default=None, min_length=1, max_length=100)
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=50)
    capabilities: list[str] | None = None
    input_types: list[str] | None = None
    output_types: list[str] | None = None
    context_window: int | None = Field(default=None, ge=0)
    max_output: int | None = Field(default=None, ge=0)
    logo_url: str | None = Field(default=None, max_length=500)
    docs_url: str | None = Field(default=None, max_length=500)
    featured: bool | None = None
    is_new: bool | None = None
    sort_order: int | None = None
    enabled: bool | None = None


class MarketModelOut(BaseModel):
    id: UUID
    slug: str
    name: str
    provider_id: str
    provider_name: str
    model_id: str
    description: str
    category: str
    capabilities: list[str]
    input_types: list[str]
    output_types: list[str]
    context_window: int
    max_output: int | None
    logo_url: str
    docs_url: str
    featured: bool
    is_new: bool
    sort_order: int
    enabled: bool
    available: bool


def _validate_public_url(value: str) -> str:
    """Admin-entered links may be site-relative or http(s); never javascript: etc."""
    if value == "":
        return value
    if value.startswith("/") and not value.startswith("//"):
        return value
    if value.lower().startswith(("http://", "https://")):
        return value
    raise ValueError("URL must be site-relative or http(s)")


class HomePlacementCreate(BaseModel):
    kind: Literal["banner", "featured", "activity"] = "banner"
    title: str = Field(min_length=1, max_length=120)
    subtitle: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=2000)
    image_url: str = Field(default="", max_length=500)
    link_url: str = Field(default="", max_length=500)
    link_label: str = Field(default="", max_length=50)
    sort_order: int = 100
    enabled: bool = True
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator(
        "title", "subtitle", "body", "image_url", "link_url", "link_label", mode="before"
    )
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("image_url", "link_url")
    @classmethod
    def validate_urls(cls, value: str) -> str:
        return _validate_public_url(value)

    @model_validator(mode="after")
    def validate_window(self) -> "HomePlacementCreate":
        if (
            self.starts_at is not None
            and self.ends_at is not None
            and self.ends_at <= self.starts_at
        ):
            raise ValueError("ends_at must be after starts_at")
        return self


class HomePlacementUpdate(BaseModel):
    kind: Literal["banner", "featured", "activity"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)
    subtitle: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=2000)
    image_url: str | None = Field(default=None, max_length=500)
    link_url: str | None = Field(default=None, max_length=500)
    link_label: str | None = Field(default=None, max_length=50)
    sort_order: int | None = None
    enabled: bool | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator(
        "title", "subtitle", "body", "image_url", "link_url", "link_label", mode="before"
    )
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("image_url", "link_url")
    @classmethod
    def validate_urls(cls, value: str | None) -> str | None:
        return None if value is None else _validate_public_url(value)


class HomePlacementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    title: str
    subtitle: str
    body: str
    image_url: str
    link_url: str
    link_label: str
    sort_order: int
    enabled: bool
    starts_at: datetime | None
    ends_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=500)
    body: str = Field(min_length=1, max_length=20000)
    cover_url: str = Field(default="", max_length=500)
    category: Literal["notice", "update", "event", "maintenance"] = "notice"
    pinned: bool = False
    status: Literal["draft", "published", "archived"] = "draft"
    published_at: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("title", "summary", "body", "cover_url", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("cover_url")
    @classmethod
    def validate_cover(cls, value: str) -> str:
        return _validate_public_url(value)

    @model_validator(mode="after")
    def validate_window(self) -> "AnnouncementCreate":
        if (
            self.published_at is not None
            and self.expires_at is not None
            and self.expires_at <= self.published_at
        ):
            raise ValueError("expires_at must be after published_at")
        return self


class AnnouncementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, min_length=1, max_length=20000)
    cover_url: str | None = Field(default=None, max_length=500)
    category: Literal["notice", "update", "event", "maintenance"] | None = None
    pinned: bool | None = None
    status: Literal["draft", "published", "archived"] | None = None
    published_at: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("title", "summary", "body", "cover_url", mode="before")
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("cover_url")
    @classmethod
    def validate_cover(cls, value: str | None) -> str | None:
        return None if value is None else _validate_public_url(value)


class AnnouncementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    summary: str
    body: str
    cover_url: str
    category: str
    pinned: bool
    status: str
    published_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NotificationOut(AnnouncementOut):
    read_at: datetime | None = None


class NotificationFeedOut(BaseModel):
    unread_count: int
    items: list[NotificationOut]


class NotificationMarkAllOut(BaseModel):
    marked: int


class HomeFeedOut(BaseModel):
    banners: list[HomePlacementOut]
    featured: list[HomePlacementOut]
    activities: list[HomePlacementOut]
    announcements: list[AnnouncementOut]


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    mime: str
    size_bytes: int
    status: str
    error_code: str | None
    page_count: int | None
    created_at: datetime


class DocumentUploadOut(BaseModel):
    id: UUID
    status: str
    duplicate: bool = False


class UsageBucketOut(BaseModel):
    key: str
    requests: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class UsageSummaryOut(BaseModel):
    start: datetime
    end: datetime
    group_by: str
    buckets: list[UsageBucketOut] = Field(default_factory=list)


class UsageCostBucketOut(UsageBucketOut):
    cost: float
    unpriced_requests: int


class UsageCostOut(BaseModel):
    start: datetime
    end: datetime
    group_by: str
    total_cost: float
    unpriced_requests: int
    buckets: list[UsageCostBucketOut] = Field(default_factory=list)


class UsageByKeyBucketOut(BaseModel):
    api_key_id: UUID | None
    name: str
    prefix: str | None
    requests: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    unpriced_requests: int


class UsageByKeyOut(BaseModel):
    start: datetime
    end: datetime
    total_requests: int
    total_cost: float
    unpriced_requests: int
    buckets: list[UsageByKeyBucketOut] = Field(default_factory=list)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[Literal["chat:write", "kb:read", "workflow:run"]] | None = None
    expires_at: datetime | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=10000)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _future_expiry(self) -> "ApiKeyCreate":
        if self.expires_at is not None and self.expires_at <= datetime.now(UTC):
            raise ValueError("expires_at must be in the future")
        return self


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    expires_at: datetime | None = None
    rate_limit_per_minute: int | None = None

    @field_validator("scopes", mode="before")
    @classmethod
    def split_scopes(cls, value: object) -> object:
        return value.split(",") if isinstance(value, str) else value


class ApiKeyCreatedOut(ApiKeyOut):
    key: str


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    plan: str
    is_personal: bool
    role: str
    created_at: datetime


class MemberCreate(_NormalizedEmailModel):
    pass


class MemberOut(BaseModel):
    user_id: UUID
    email: EmailStr
    role: str
    created_at: datetime


class QuotaWindowOut(BaseModel):
    limit: int
    used: int
    remaining: int
    reset_seconds: int


class QuotaSummaryOut(BaseModel):
    plan: str
    requests: QuotaWindowOut
    tokens: QuotaWindowOut
    max_keys: int
    active_keys: int


class TraceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_id: str
    conversation_id: UUID | None
    message_id: UUID | None
    provider_id: str | None
    model: str | None
    retrieval_ms: float | None
    ttft_ms: float | None
    total_ms: float | None
    status: str
    error_code: str | None
    attempts: int
    agents: list[dict[str, object]] | None = None
    created_at: datetime


class ModelOut(BaseModel):
    id: str
    provider_id: str
    model_id: str
    display_name: str
    context_window: int
    input_price: float
    output_price: float
    tags: list[str]
    priority: int
    available: bool


class AdminWorkspaceOut(BaseModel):
    id: UUID
    name: str
    plan: str
    is_personal: bool
    member_count: int
    created_at: datetime


class AdminMemberOut(BaseModel):
    user_id: UUID
    email: EmailStr
    role: str
    created_at: datetime


class AdminPlanChangeIn(BaseModel):
    plan: Literal["free", "pro"]


class AdminRunCountsOut(BaseModel):
    total: int
    failed: int
    failure_rate: float


class AdminRunSummaryOut(BaseModel):
    workflows: AdminRunCountsOut
    collaborations: AdminRunCountsOut


class AdminModelToggleIn(BaseModel):
    enabled: bool


class AdminModelOut(BaseModel):
    id: UUID
    provider_id: str
    model_id: str
    display_name: str
    enabled: bool


class AdminUsageBucketOut(BaseModel):
    key: str
    requests: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    unpriced_requests: int


class AdminUsageOut(BaseModel):
    start: datetime
    end: datetime
    group_by: str
    requests: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_cost: float
    unpriced_requests: int
    buckets: list[AdminUsageBucketOut] = Field(default_factory=list)


class AuditLogOut(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    actor_email: EmailStr | None
    action: str
    target_type: str
    target_id: str | None
    detail: dict[str, object] | None
    created_at: datetime
