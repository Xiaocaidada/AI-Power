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


class KnowledgeBaseSettingsUpdate(BaseModel):
    chunking: ChunkingSettingsUpdate | None = None
    retrieval: RetrievalSettingsUpdate | None = None


class ChunkingSettingsOut(BaseModel):
    chunk_size: int
    chunk_overlap: int


class RetrievalSettingsOut(BaseModel):
    top_k: int
    candidate_k: int
    hybrid_enabled: bool
    rerank_enabled: bool


class KnowledgeBaseSettingsOut(BaseModel):
    chunking: ChunkingSettingsOut
    retrieval: RetrievalSettingsOut


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
    status: str
    input_text: str
    error_code: str | None
    prompt_tokens: int
    completion_tokens: int
    cost: float
    total_ms: float | None
    started_at: datetime
    finished_at: datetime | None
    nodes: list[WorkflowNodeRunOut] = Field(default_factory=list)


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


class ConversationCreate(BaseModel):
    provider_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=200)
    kb_id: UUID | None = None
    agent: bool = False
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
    agent: bool = False
    prompt_version_id: UUID | None = None
    created_at: datetime


class CitationOut(BaseModel):
    index: int
    document_id: UUID
    chunk_id: UUID
    page_no: int | None
    snippet: str


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
    created_at: datetime
    citations: list[CitationOut] = Field(default_factory=list)


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut] = Field(default_factory=list)


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
