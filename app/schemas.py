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
    description: str = Field(default="", max_length=500)

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class KnowledgeBaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str = ""
    created_at: datetime


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_optional(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ChunkingSettingsUpdate(BaseModel):
    chunk_size: int | None = Field(default=None, ge=50, le=4000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=1000)


class RetrievalSettingsUpdate(BaseModel):
    top_k: int | None = Field(default=None, ge=1, le=20)
    candidate_k: int | None = Field(default=None, ge=1, le=100)
    hybrid_enabled: bool | None = None
    rerank_enabled: bool | None = None
    metadata_filter: dict[str, str] | None = None


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
    metadata_filter: dict[str, str] = Field(default_factory=dict)


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
    retrieval_workflow_version_id: UUID | None = None
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
    retrieval_workflow_version_id: UUID | None
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
    precision_at_5: float
    recall_at_5: float
    ndcg_at_5: float
    precision_at_10: float
    recall_at_10: float
    ndcg_at_10: float
    retrieval_mode: str | None
    retrieval_trace: list[dict[str, object]]
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


class EvalNodeTimingOut(BaseModel):
    node_type: str
    runs: int
    failures: int
    avg_ms: float
    avg_count: float


class EvalQuestionInsightOut(BaseModel):
    question_id: UUID
    question_text: str
    hit_rank: int | None
    precision_at_5: float
    recall_at_5: float
    ndcg_at_5: float
    latency_ms: float | None
    retrieval_mode: str | None
    error_code: str | None


class EvalRunAnalysisOut(BaseModel):
    run: EvalRunOut
    node_timing: list[EvalNodeTimingOut]
    worst_questions: list[EvalQuestionInsightOut]
    missed_questions: list[EvalQuestionInsightOut]
    slowest_questions: list[EvalQuestionInsightOut]


class KnowledgeOptimizationCreate(BaseModel):
    eval_run_id: UUID
    provider_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=200)

    @field_validator("provider_id", "model", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class KnowledgeOptimizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kb_id: UUID
    eval_run_id: UUID | None
    workflow_id: UUID | None
    base_version_id: UUID | None
    applied_version_id: UUID | None
    previous_binding_version_id: UUID | None
    status: str
    summary: str
    rationale: str
    suggestions: list[dict[str, object]]
    metrics_snapshot: dict[str, object]
    provider_id: str | None
    model: str | None
    error_code: str | None
    created_at: datetime
    applied_at: datetime | None
    reverted_at: datetime | None


class KnowledgeOptimizationDetailOut(KnowledgeOptimizationOut):
    proposed_definition: dict[str, object] | None
    diff: dict[str, object] | None


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
    kind: Literal["agent", "knowledge_process", "knowledge_retrieval"] = "agent"
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


class WorkflowDraftIn(BaseModel):
    definition: dict[str, object]


class WorkflowDraftOut(BaseModel):
    definition: dict[str, object] | None = None
    saved_at: datetime | None = None


class WorkflowOut(BaseModel):
    id: UUID
    name: str
    description: str
    kind: str = "agent"
    created_at: datetime
    versions: list[WorkflowVersionOut] = Field(default_factory=list)
    draft_definition: dict[str, object] | None = None
    draft_saved_at: datetime | None = None


class WorkflowRunCreate(BaseModel):
    version: int | None = None
    input: str = Field(default="", max_length=20000)
    kb_id: UUID | None = None
    document_id: UUID | None = None
    start_node_id: str | None = Field(default=None, max_length=120)
    node_outputs: dict[str, str] = Field(default_factory=dict)

    @field_validator("input", mode="before")
    @classmethod
    def strip_input(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class WorkflowNodeDebugIn(BaseModel):
    version: int | None = None
    input: str = Field(default="", max_length=20000)
    node_outputs: dict[str, str] = Field(default_factory=dict)


class WorkflowNodeDebugOut(BaseModel):
    run_id: UUID
    node_id: str
    node_type: str
    status: str
    output: str = ""
    input_summary: str = ""
    error_code: str | None = None
    duration_ms: float = 0.0
    node_run_id: UUID | None = None


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
    input_payload: dict = Field(default_factory=dict)
    output_payload: dict = Field(default_factory=dict)
    applied_at: datetime | None = None
    error_code: str | None
    cancel_requested_at: datetime | None
    prompt_tokens: int
    completion_tokens: int
    cost: float
    total_ms: float | None
    started_at: datetime
    finished_at: datetime | None
    nodes: list[WorkflowNodeRunOut] = Field(default_factory=list)


class KnowledgeProcessBindingIn(BaseModel):
    workflow_version_id: UUID | None = None


class KnowledgeProcessBindingOut(BaseModel):
    workflow_version_id: UUID | None = None
    workflow_id: UUID | None = None
    version: int | None = None
    kind: str = "knowledge_process"
    name: str = ""


class KnowledgeProcessArtifactOut(BaseModel):
    node_id: str
    kind: str
    payload: dict = Field(default_factory=dict)


class KnowledgeProcessPreviewOut(BaseModel):
    run: WorkflowRunOut
    artifacts: list[KnowledgeProcessArtifactOut] = Field(default_factory=list)
    drafts: list[dict] = Field(default_factory=list)
    draft_count: int = 0
    applied: bool = False


class KnowledgeRetrievalTestIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    workflow_version_id: UUID | None = None
    top_k: int = Field(default=8, ge=1, le=50)

    @field_validator("query", mode="before")
    @classmethod
    def strip_query(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class KnowledgeRetrievalTestOut(BaseModel):
    query: str
    rewritten_query: str = ""
    mode: str = "builtin"
    context: str = ""
    results: list[RetrievalHitOut] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)
    nodes: list[dict] = Field(default_factory=list)
    timings: dict = Field(default_factory=dict)


class KnowledgeProcessApplyOut(BaseModel):
    document_id: UUID
    chunks: int
    applied_at: datetime


class RunAcceptedOut(BaseModel):
    run_id: UUID
    status: str = "queued"


class RunCancelOut(BaseModel):
    run_id: UUID
    status: str
    cancel_requested_at: datetime | None


class PromptVariableDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=200)
    required: bool = True
    default: str = Field(default="", max_length=2000)


class GenerationSettings(BaseModel):
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None


class PromptVersionCreate(BaseModel):
    system_prompt: str = Field(min_length=1, max_length=20000)
    user_prompt: str = Field(default="", max_length=20000)
    variable_definitions: list[PromptVariableDefinition] = Field(
        default_factory=list, max_length=50
    )
    parameters: GenerationSettings = Field(default_factory=GenerationSettings)

    @field_validator("system_prompt", "user_prompt", mode="before")
    @classmethod
    def strip_prompt(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PromptTemplateCreate(PromptVersionCreate):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="general", max_length=50)

    @field_validator("name", "description", "category", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PromptTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=50)

    @field_validator("name", "description", "category", mode="before")
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PromptFavoriteOut(BaseModel):
    favorite: bool


class PromptRenderIn(BaseModel):
    version: int | None = None
    variables: dict[str, str] = Field(default_factory=dict)


class PromptVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    system_prompt: str
    user_prompt: str = ""
    variables: list[str]
    variable_definitions: list[dict] = Field(default_factory=list)
    parameters: dict = Field(default_factory=dict)
    created_at: datetime


class PromptTemplateOut(BaseModel):
    id: UUID
    name: str
    description: str
    category: str = "general"
    scope: str = "workspace"
    favorite: bool = False
    created_at: datetime
    versions: list[PromptVersionOut] = Field(default_factory=list)


class PromptRenderOut(BaseModel):
    rendered: str
    system_prompt: str = ""
    user_prompt: str = ""
    version: int
    variables: list[str]
    missing: list[str] = Field(default_factory=list)


class PromptDiffLineOut(BaseModel):
    type: Literal["equal", "insert", "delete"]
    old_line: int | None = None
    new_line: int | None = None
    text: str = ""


class PromptDiffOut(BaseModel):
    from_version: int
    to_version: int
    system: list[PromptDiffLineOut] = Field(default_factory=list)
    user: list[PromptDiffLineOut] = Field(default_factory=list)


class ArenaModelIn(BaseModel):
    provider_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=200)


class PromptExperimentCreate(BaseModel):
    template_id: UUID
    version: int | None = None
    variables: dict[str, str] = Field(default_factory=dict)
    models: list[ArenaModelIn] = Field(min_length=1, max_length=4)
    parameters: GenerationSettings = Field(default_factory=GenerationSettings)


class PromptExperimentOutputOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: str
    model: str
    status: str
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost: float = 0.0
    ttft_ms: float | None = None
    total_ms: float | None = None
    error_code: str | None = None


class PromptExperimentOut(BaseModel):
    id: UUID
    template_id: UUID | None
    version_id: UUID | None
    system_prompt: str
    user_prompt: str
    variables: dict
    parameters: dict
    rating: str | None = None
    note: str = ""
    created_at: datetime
    outputs: list[PromptExperimentOutputOut] = Field(default_factory=list)


class PromptExperimentUpdate(BaseModel):
    rating: str | None = Field(default=None, pattern="^(good|bad)$")
    note: str = Field(default="", max_length=1000)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=20000)
    default_provider_id: str | None = Field(default=None, max_length=50)
    default_model: str | None = Field(default=None, max_length=200)
    default_kb_id: UUID | None = None
    kb_ids: list[UUID] = Field(default_factory=list, max_length=10)
    default_custom_agent_id: UUID | None = None
    default_agent: bool = False
    memory_enabled: bool | None = None
    allow_global_memory: bool = True
    allow_agent_writes: bool = False

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
    kb_ids: list[UUID] | None = Field(default=None, max_length=10)
    default_custom_agent_id: UUID | None = None
    default_agent: bool | None = None
    memory_enabled: bool | None = None
    allow_global_memory: bool | None = None
    allow_agent_writes: bool | None = None
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
    kb_ids: list[UUID] = Field(default_factory=list)
    default_custom_agent_id: UUID | None = None
    default_agent: bool
    memory_enabled: bool | None = None
    allow_global_memory: bool = True
    allow_agent_writes: bool = False
    archived: bool
    conversation_count: int
    owned: bool
    created_at: datetime
    updated_at: datetime


class CustomAgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(min_length=1, max_length=20000)
    category: str = Field(default="general", max_length=40)
    mode: Literal["autonomous", "workflow", "hybrid"] = "autonomous"
    icon: str = Field(default="🤖", max_length=32)
    welcome_message: str = Field(default="", max_length=1000)
    examples: list[str] = Field(default_factory=list, max_length=10)
    usage_instructions: str = Field(default="", max_length=5000)
    generation_settings: dict = Field(default_factory=dict)
    default_provider_id: str | None = Field(default=None, max_length=50)
    default_model: str | None = Field(default=None, max_length=200)
    default_kb_id: UUID | None = None
    kb_ids: list[UUID] = Field(default_factory=list, max_length=10)
    tools: list[str] = Field(default_factory=list, max_length=20)
    plugin_ids: list[UUID] = Field(default_factory=list, max_length=20)
    workflow_id: UUID | None = None
    visibility: Literal["private", "shared"] = "private"
    allow_copy: bool = True
    show_structure: bool = True
    memory_enabled: bool = False
    memory_read_global: bool = True
    memory_read_project: bool = True
    memory_read_agent: bool = True
    memory_write: bool = False
    memory_write_scope: Literal["global", "project", "agent"] = "agent"
    memory_write_mode: Literal["candidate", "create", "upsert"] = "candidate"

    @field_validator(
        "name", "description", "instructions", "category", "default_provider_id",
        "default_model", mode="before",
    )
    @classmethod
    def strip_custom_agent_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CustomAgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    instructions: str | None = Field(default=None, min_length=1, max_length=20000)
    category: str | None = Field(default=None, max_length=40)
    mode: Literal["autonomous", "workflow", "hybrid"] | None = None
    icon: str | None = Field(default=None, max_length=32)
    welcome_message: str | None = Field(default=None, max_length=1000)
    examples: list[str] | None = Field(default=None, max_length=10)
    usage_instructions: str | None = Field(default=None, max_length=5000)
    generation_settings: dict | None = None
    default_provider_id: str | None = Field(default=None, max_length=50)
    default_model: str | None = Field(default=None, max_length=200)
    default_kb_id: UUID | None = None
    kb_ids: list[UUID] | None = Field(default=None, max_length=10)
    tools: list[str] | None = Field(default=None, max_length=20)
    plugin_ids: list[UUID] | None = Field(default=None, max_length=20)
    workflow_id: UUID | None = None
    visibility: Literal["private", "shared"] | None = None
    enabled: bool | None = None
    allow_copy: bool | None = None
    show_structure: bool | None = None
    memory_enabled: bool | None = None
    memory_read_global: bool | None = None
    memory_read_project: bool | None = None
    memory_read_agent: bool | None = None
    memory_write: bool | None = None
    memory_write_scope: Literal["global", "project", "agent"] | None = None
    memory_write_mode: Literal["candidate", "create", "upsert"] | None = None

    @field_validator(
        "name", "description", "instructions", "category", "default_provider_id",
        "default_model", mode="before",
    )
    @classmethod
    def strip_custom_agent_optional(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CustomAgentOut(BaseModel):
    id: str
    name: str
    description: str
    instructions: str
    category: str
    mode: str = "autonomous"
    icon: str = "🤖"
    welcome_message: str = ""
    examples: list[str] = Field(default_factory=list)
    usage_instructions: str = ""
    generation_settings: dict = Field(default_factory=dict)
    default_provider_id: str | None
    default_model: str | None
    default_kb_id: UUID | None
    kb_ids: list[UUID] = Field(default_factory=list)
    tools: list[str]
    plugin_ids: list[UUID]
    workflow_id: UUID | None = None
    visibility: str
    enabled: bool
    memory_enabled: bool = False
    memory_read_global: bool = True
    memory_read_project: bool = True
    memory_read_agent: bool = True
    memory_write: bool = False
    memory_write_scope: Literal["global", "project", "agent"] = "agent"
    memory_write_mode: Literal["candidate", "create", "upsert"] = "candidate"
    rating_avg: float = 0.0
    rating_count: int = 0
    archived: bool
    owned: bool
    builtin: bool
    published: bool = False
    featured: bool = False
    public_slug: str | None = None
    allow_copy: bool = True
    show_structure: bool = True
    favorite: bool = False
    favorite_count: int = 0
    usage_count: int = 0
    copy_count: int = 0
    conversation_count: int
    created_at: datetime | None
    updated_at: datetime | None


class AgentPublishIn(BaseModel):
    slug: str = Field(default="", max_length=80)
    allow_copy: bool = True
    show_structure: bool = True


class AgentFavoriteOut(BaseModel):
    favorite: bool


class AgentUseOut(BaseModel):
    usage_count: int


class AgentFeatureIn(BaseModel):
    featured: bool


class AgentRunOut(BaseModel):
    id: UUID
    kind: Literal["chat", "workflow"]
    title: str = ""
    status: str
    input: str = ""
    output: str = ""
    model: str = ""
    duration_ms: float | None = None
    error_code: str | None = None
    created_at: datetime
    href: str = ""


class AgentMarketOut(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str
    icon: str
    category: str
    mode: str
    featured: bool = False
    usage_count: int = 0
    favorite_count: int = 0
    copy_count: int = 0
    rating_avg: float = 0.0
    rating_count: int = 0
    allow_copy: bool = True
    published_at: datetime | None = None


class AgentReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    content: str = Field(default="", max_length=2000)


class AgentReviewOut(BaseModel):
    id: UUID
    rating: int
    content: str
    author: str
    created_at: datetime
    updated_at: datetime


class AdminReviewOut(BaseModel):
    id: UUID
    agent_id: UUID
    agent_name: str
    author: str
    rating: int
    content: str
    status: str
    created_at: datetime
    updated_at: datetime


class ReviewVisibilityIn(BaseModel):
    visible: bool


class AgentReviewListOut(BaseModel):
    rating_avg: float
    rating_count: int
    reviews: list[AgentReviewOut] = Field(default_factory=list)


class AgentReportIn(BaseModel):
    reason: Literal["spam", "abuse", "copyright", "misleading", "other"]
    detail: str = Field(default="", max_length=2000)


class AgentReportOut(BaseModel):
    id: UUID
    agent_id: UUID
    agent_name: str
    reporter: str
    reason: str
    detail: str
    status: str
    resolution: str = ""
    created_at: datetime
    handled_at: datetime | None = None


class AgentReportResolveIn(BaseModel):
    action: Literal["dismiss", "unpublish"]
    resolution: str = Field(default="", max_length=500)


class WorkflowReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    node_id: str
    status: str
    prompt: str
    decision: str
    comment: str
    output: str
    reviewer_user_id: UUID | None = None
    created_at: datetime
    expires_at: datetime | None = None
    resolved_at: datetime | None = None


class WorkflowReviewRespondIn(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field(default="", max_length=2000)
    output: str = Field(default="", max_length=20000)


MemoryScopeType = Literal["global", "project", "agent"]
MemoryCategory = Literal[
    "fact",
    "preference",
    "profile",
    "project",
    "technical",
    "experience",
    "decision",
    "relation",
    "summary",
]
MemoryStatus = Literal[
    "candidate", "active", "conflict", "expired", "archived", "rejected"
]


def _clean_memory_tags(value: object) -> object:
    if not isinstance(value, list):
        return value
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        tag = item.strip()[:30]
        if tag and tag not in cleaned:
            cleaned.append(tag)
    return cleaned[:20]


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    title: str = Field(default="", max_length=120)
    scope: Literal["user", "workspace"] = "user"
    kind: Literal["fact", "preference", "summary"] = "fact"
    agent_id: UUID | None = None
    project_id: UUID | None = None
    scope_type: MemoryScopeType | None = None
    category: MemoryCategory | None = None
    status: MemoryStatus = "active"
    importance: int = Field(default=3, ge=1, le=5)
    tags: list[str] = Field(default_factory=list, max_length=20)
    source_type: str | None = Field(default=None, max_length=30)
    source_id: str | None = Field(default=None, max_length=100)
    source_ref: dict[str, object] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0, le=1)
    sensitivity: Literal["normal", "sensitive"] = "normal"
    enabled: bool = True
    pinned: bool = False
    favorite: bool = False
    valid_until: datetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value: object) -> object:
        return _clean_memory_tags(value)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=10000)
    title: str | None = Field(default=None, max_length=120)
    scope: Literal["user", "workspace"] | None = None
    kind: Literal["fact", "preference", "summary"] | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    agent_id: UUID | None = None
    project_id: UUID | None = None
    scope_type: MemoryScopeType | None = None
    category: MemoryCategory | None = None
    status: MemoryStatus | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    enabled: bool | None = None
    pinned: bool | None = None
    favorite: bool | None = None
    sensitivity: Literal["normal", "sensitive"] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    valid_until: datetime | None = None
    metadata: dict[str, object] | None = None
    change_reason: str = Field(default="", max_length=300)

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value: object) -> object:
        return _clean_memory_tags(value)


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    agent_id: UUID | None = None
    project_id: UUID | None = None
    scope: str
    scope_type: str
    kind: str
    category: str
    status: str
    title: str
    content: str
    importance: int
    source: str
    source_type: str
    source_id: str | None = None
    source_ref: dict[str, object] = Field(default_factory=dict)
    confidence: float
    sensitivity: str
    enabled: bool
    pinned: bool
    favorite: bool
    tags: list[str] = Field(default_factory=list)
    valid_until: datetime | None = None
    use_count: int
    version: int
    metadata: dict[str, object] = Field(
        default_factory=dict,
        validation_alias="memory_metadata",
        serialization_alias="metadata",
    )
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MemoryVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    snapshot: dict[str, object]
    changed_by: UUID | None = None
    change_reason: str
    created_at: datetime


class MemoryRelationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    from_type: str
    from_id: UUID
    to_type: str
    to_id: UUID
    relation_type: str
    confidence: float
    basis: str
    source: str
    created_at: datetime


class MemoryGraphNode(BaseModel):
    id: str
    type: Literal["memory", "project", "agent", "document"]
    label: str
    memory_id: UUID | None = None
    ref_id: UUID | None = None
    category: str | None = None
    scope_type: str | None = None
    status: str | None = None
    pinned: bool = False
    importance: int | None = None


class MemoryGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relation_type: str
    confidence: float = 1.0
    basis: str = ""
    source_kind: str = "manual"


class MemoryGraphStats(BaseModel):
    memories: int = 0
    external: int = 0
    relations: int = 0
    orphans: int = 0


class MemoryGraphOut(BaseModel):
    nodes: list[MemoryGraphNode] = Field(default_factory=list)
    edges: list[MemoryGraphEdge] = Field(default_factory=list)
    stats: MemoryGraphStats = Field(default_factory=MemoryGraphStats)


class MemoryGraphRebuildOut(BaseModel):
    created: int
    memories: int


class MemoryQualityAnalysisOut(BaseModel):
    total: int = 0
    duplicates: int = 0
    duplicate_groups: list[list[str]] = Field(default_factory=list)
    conflicts: int = 0
    expired: int = 0
    unused: int = 0
    missing_source: int = 0
    incomplete: int = 0
    orphans: int = 0


class MemoryOptimizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    status: str
    title: str
    reason: str
    expected_effect: str
    memory_ids: list[str] = Field(default_factory=list)
    payload: dict[str, object] = Field(default_factory=dict)
    applied_at: datetime | None = None
    rolled_back_at: datetime | None = None
    created_at: datetime


class MemoryQualityOut(BaseModel):
    analysis: MemoryQualityAnalysisOut
    suggestions: list[MemoryOptimizationOut] = Field(default_factory=list)


class MemoryEvalCaseIn(BaseModel):
    name: str = Field(default="", max_length=120)
    query: str = Field(min_length=1, max_length=2000)
    expected_memory_ids: list[UUID] = Field(default_factory=list, max_length=20)
    project_id: UUID | None = None
    agent_id: UUID | None = None
    notes: str = Field(default="", max_length=500)


class MemoryEvalCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    query: str
    expected_memory_ids: list[str] = Field(default_factory=list)
    project_id: UUID | None = None
    agent_id: UUID | None = None
    notes: str
    created_at: datetime
    updated_at: datetime


class MemoryEvalRunIn(BaseModel):
    top_k: int = Field(default=5, ge=1, le=20)


class MemoryEvalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    cases_count: int
    metrics: dict[str, object] = Field(default_factory=dict)
    results: list[dict[str, object]] = Field(default_factory=list)
    duration_ms: float
    created_at: datetime


class MemoryRelationIn(BaseModel):
    to_type: Literal["memory", "project", "document", "agent"] = "memory"
    to_id: UUID
    relation_type: Literal[
        "related", "supports", "contradicts", "supersedes", "derived_from"
    ] = "related"
    basis: str = Field(default="", max_length=500)


class MemoryUsageOut(BaseModel):
    id: UUID
    memory_id: UUID
    memory_title: str
    context_type: str
    context_id: str | None = None
    provider_id: str | None = None
    model: str | None = None
    relevance: float | None = None
    injected_chars: int
    created_at: datetime


class MemoryCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None = None
    agent_id: UUID | None = None
    target_memory_id: UUID | None = None
    source_type: str
    source_id: str | None = None
    source_ref: dict[str, object] = Field(default_factory=dict)
    extracted_by: str | None = None
    suggested_action: str
    category: str
    scope_type: str
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    confidence: float
    sensitivity: str
    status: str
    reason: str
    created_at: datetime
    reviewed_at: datetime | None = None


class MemoryCandidateAcceptIn(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    content: str | None = Field(default=None, min_length=1, max_length=10000)
    category: MemoryCategory | None = None
    scope_type: MemoryScopeType | None = None
    tags: list[str] | None = Field(default=None, max_length=20)

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value: object) -> object:
        return _clean_memory_tags(value)


class MemoryStatsOut(BaseModel):
    total: int
    active: int
    pending: int
    candidates_pending: int = 0
    conflict: int
    expired: int
    archived: int
    by_category: dict[str, int] = Field(default_factory=dict)
    by_scope: dict[str, int] = Field(default_factory=dict)
    recent: list[MemoryOut] = Field(default_factory=list)
    top_used: list[MemoryOut] = Field(default_factory=list)


class MemorySettingsIn(BaseModel):
    enabled: bool | None = None
    auto_extract: bool | None = None
    auto_save: bool | None = None
    require_confirmation: bool | None = None
    allowed_categories: list[MemoryCategory] | None = Field(default=None, max_length=20)
    allow_project_extract: bool | None = None
    allow_agent_extract: bool | None = None
    allow_cross_model: bool | None = None
    max_inject_items: int | None = Field(default=None, ge=1, le=50)
    max_inject_chars: int | None = Field(default=None, ge=200, le=20000)
    blocked_topics: list[str] | None = Field(default=None, max_length=20)
    retention_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("blocked_topics", mode="before")
    @classmethod
    def clean_blocked(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            topic = item.strip()[:50]
            if topic and topic not in cleaned:
                cleaned.append(topic)
        return cleaned[:20]


class MemorySettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    auto_extract: bool
    auto_save: bool
    require_confirmation: bool
    allowed_categories: list[str]
    allow_project_extract: bool
    allow_agent_extract: bool
    allow_cross_model: bool
    max_inject_items: int
    max_inject_chars: int
    blocked_topics: list[str]
    retention_days: int | None
    updated_at: datetime


class MemoryBatchIn(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=100)
    status: MemoryStatus | None = None
    category: MemoryCategory | None = None
    scope_type: MemoryScopeType | None = None
    project_id: UUID | None = None
    agent_id: UUID | None = None
    enabled: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=20)


class MemoryBatchOut(BaseModel):
    updated: int


class McpServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    endpoint_url: str = Field(min_length=1, max_length=1000)
    auth_token: str | None = Field(default=None, max_length=500)
    enabled: bool = True
    timeout_seconds: int = Field(default=20, ge=1, le=120)


class McpServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    endpoint_url: str | None = Field(default=None, min_length=1, max_length=1000)
    auth_token: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=120)


class McpServerOut(BaseModel):
    id: UUID
    name: str
    description: str
    endpoint_url: str
    enabled: bool
    timeout_seconds: int
    auth_hint: str = ""
    created_at: datetime
    updated_at: datetime


class DatabaseConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    dsn: str = Field(min_length=1, max_length=2000)
    enabled: bool = True
    max_rows: int = Field(default=100, ge=1, le=500)
    timeout_seconds: int = Field(default=15, ge=1, le=120)


class DatabaseConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    dsn: str | None = Field(default=None, min_length=1, max_length=2000)
    enabled: bool | None = None
    max_rows: int | None = Field(default=None, ge=1, le=500)
    timeout_seconds: int | None = Field(default=None, ge=1, le=120)


class DatabaseConnectionOut(BaseModel):
    id: UUID
    name: str
    description: str
    enabled: bool
    max_rows: int
    timeout_seconds: int
    dsn_hint: str = ""
    created_at: datetime
    updated_at: datetime


class DatabaseConnectionOptionOut(BaseModel):
    id: UUID
    name: str
    description: str = ""


class McpResourceOut(BaseModel):
    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""


class McpPromptOut(BaseModel):
    name: str
    description: str = ""
    arguments: list = Field(default_factory=list)


class McpServerOptionOut(BaseModel):
    id: UUID
    name: str
    description: str = ""


class McpToolOut(BaseModel):
    name: str
    description: str = ""
    input_schema: dict = Field(default_factory=dict)


class AgentMarketDetail(AgentMarketOut):
    welcome_message: str = ""
    examples: list[str] = Field(default_factory=list)
    usage_instructions: str = ""
    tools: list[str] = Field(default_factory=list)
    model_hint: str = ""
    kb_requirements: list[str] = Field(default_factory=list)
    plugin_requirements: list[str] = Field(default_factory=list)
    instructions: str | None = None
    workflow: dict | None = None


class AgentBuilderIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    provider_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=200)
    current_definition: dict | None = None
    agent_id: UUID | None = None


class AgentBuilderOut(BaseModel):
    definition: dict
    summary: str = ""
    missing_resources: list[str] = Field(default_factory=list)
    provider_id: str
    model: str


class AgentBuilderSessionCreate(BaseModel):
    scope: Literal["agent", "knowledge_process", "knowledge_retrieval"] = "agent"
    agent_id: UUID | None = None
    workflow_id: UUID | None = None
    provider_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=200)
    draft_definition: dict | None = None


class AgentBuilderSessionOut(BaseModel):
    id: UUID
    scope: str = "agent"
    agent_id: UUID | None = None
    workflow_id: UUID | None = None
    provider_id: str
    model: str
    messages: list[dict] = Field(default_factory=list)
    draft_definition: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AgentBuilderMessageIn(BaseModel):
    kind: Literal["generate", "modify", "explain", "fix"] = "modify"
    prompt: str = Field(min_length=1, max_length=20000)
    current_definition: dict | None = None
    run_id: UUID | None = None


class AgentBuilderApplyIn(BaseModel):
    definition: dict


class AgentBuilderNodeChange(BaseModel):
    field: str
    before: object | None = None
    after: object | None = None


class AgentBuilderNodeDiff(BaseModel):
    id: str
    type: str
    changes: list[AgentBuilderNodeChange] = Field(default_factory=list)


class AgentBuilderDiff(BaseModel):
    added_nodes: list[dict] = Field(default_factory=list)
    removed_nodes: list[dict] = Field(default_factory=list)
    updated_nodes: list[AgentBuilderNodeDiff] = Field(default_factory=list)
    added_edges: list[dict] = Field(default_factory=list)
    removed_edges: list[dict] = Field(default_factory=list)


class AgentBuilderTurnOut(BaseModel):
    session_id: UUID
    message: str = ""
    definition: dict | None = None
    diff: AgentBuilderDiff | None = None
    missing_resources: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class PluginCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="general", max_length=40)
    docs_url: str = Field(default="", max_length=500)
    endpoint_url: str = Field(min_length=1, max_length=1000)
    method: Literal["GET", "POST"] = "POST"
    auth_type: Literal["none", "bearer"] = "none"
    parameters: dict = Field(default_factory=dict)
    sensitive: bool = False
    enabled: bool = True
    timeout_seconds: int = Field(default=10, ge=1, le=30)

    @field_validator("slug", "name", "description", "category", "docs_url", "endpoint_url",
                     mode="before")
    @classmethod
    def strip_plugin_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("docs_url", "endpoint_url")
    @classmethod
    def validate_plugin_urls(cls, value: str) -> str:
        if value == "":
            return value
        if not value.lower().startswith(("http://", "https://")):
            raise ValueError("plugin URL must be absolute http(s)")
        return value


class PluginUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=40)
    docs_url: str | None = Field(default=None, max_length=500)
    endpoint_url: str | None = Field(default=None, min_length=1, max_length=1000)
    method: Literal["GET", "POST"] | None = None
    auth_type: Literal["none", "bearer"] | None = None
    parameters: dict | None = None
    sensitive: bool | None = None
    enabled: bool | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=30)

    @field_validator("name", "description", "category", "docs_url", "endpoint_url",
                     mode="before")
    @classmethod
    def strip_plugin_optional(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("docs_url", "endpoint_url")
    @classmethod
    def validate_plugin_optional_urls(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        if not value.lower().startswith(("http://", "https://")):
            raise ValueError("plugin URL must be absolute http(s)")
        return value


class PluginOut(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str
    category: str
    docs_url: str
    endpoint_url: str
    method: str
    auth_type: str
    parameters: dict
    sensitive: bool
    enabled: bool
    timeout_seconds: int
    configured: bool
    config_enabled: bool
    credential_hint: str
    status: str
    last_error: str | None
    last_checked_at: datetime | None


class PluginConfigIn(BaseModel):
    enabled: bool = True
    credential: str | None = Field(default=None, max_length=500)


class ConversationPluginOut(BaseModel):
    plugin_id: UUID
    slug: str
    name: str
    sensitive: bool
    confirmed_at: datetime | None


class ConversationPluginsIn(BaseModel):
    plugin_ids: list[UUID] = Field(default_factory=list, max_length=20)


class PluginCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plugin_id: UUID
    conversation_id: UUID | None
    status: str
    request_summary: str
    response_summary: str
    latency_ms: int
    error_code: str | None
    created_at: datetime


class ConversationCreate(BaseModel):
    provider_id: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=200)
    kb_id: UUID | None = None
    kb_ids: list[UUID] = Field(default_factory=list, max_length=10)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=10)
    agent: bool = False
    custom_agent_id: UUID | None = None
    plugin_ids: list[UUID] = Field(default_factory=list, max_length=20)
    confirmed_plugin_ids: list[UUID] = Field(default_factory=list, max_length=20)
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
    kb_ids: list[UUID] = Field(default_factory=list)
    project_id: UUID | None = None
    custom_agent_id: UUID | None = None
    agent: bool = False
    pinned: bool = False
    memory_enabled: bool | None = None
    excluded_memory_ids: list[UUID] = Field(default_factory=list)
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
    memory_enabled: bool | None = None
    excluded_memory_ids: list[UUID] | None = Field(default=None, max_length=50)
    generation_settings: GenerationSettings | None = None

    @field_validator("title", "provider_id", "model", mode="before")
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ConversationBatchIn(BaseModel):
    action: Literal["archive", "unarchive", "move", "delete"]
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


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    mime: str
    size_bytes: int
    kind: str
    status: str
    error_code: str | None = None
    created_at: datetime


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
    memory_refs: list[dict[str, object]] = Field(default_factory=list)
    reply_to_message_id: UUID | None = None
    created_at: datetime
    citations: list[CitationOut] = Field(default_factory=list)
    feedback: MessageFeedbackOut | None = None
    attachments: list[AttachmentOut] = Field(default_factory=list)


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut] = Field(default_factory=list)
    plugins: list[ConversationPluginOut] = Field(default_factory=list)


class MessageUpdateIn(BaseModel):
    content: str = Field(min_length=1, max_length=20000)

    @field_validator("content", mode="before")
    @classmethod
    def strip_content(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class MessageEditOut(BaseModel):
    message: MessageOut
    removed: int


class MessageFeedbackIn(BaseModel):
    rating: Literal["up", "down"]
    reason: str = Field(default="", max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SendMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=10)

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
    tags: list[str] = Field(default_factory=list)
    folder: str = ""
    doc_metadata: dict[str, str] = Field(default_factory=dict)
    source_url: str | None = None
    created_at: datetime


def clean_document_tags(value: object) -> object:
    if not isinstance(value, list):
        return value
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        tag = item.strip()
        if tag and tag not in cleaned and len(tag) <= 30:
            cleaned.append(tag)
    return cleaned[:20]


def clean_document_folder(value: object) -> object:
    if not isinstance(value, str):
        return value
    segments = [
        segment.strip()
        for segment in value.replace("\\", "/").split("/")
        if segment.strip()
    ]
    return "/".join(segments)[:255]


def clean_document_metadata(value: object) -> object:
    if not isinstance(value, dict):
        return value
    cleaned: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            continue
        name = key.strip()[:50]
        text = item.strip()[:500]
        if not name or not text:
            continue
        cleaned[name] = text
        if len(cleaned) >= 20:
            break
    return cleaned


class DocumentUpdate(BaseModel):
    tags: list[str] | None = Field(default=None, max_length=20)
    folder: str | None = Field(default=None, max_length=255)
    doc_metadata: dict[str, str] | None = None

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value: object) -> object:
        return clean_document_tags(value)

    @field_validator("folder", mode="before")
    @classmethod
    def clean_folder(cls, value: object) -> object:
        return clean_document_folder(value)

    @field_validator("doc_metadata", mode="before")
    @classmethod
    def clean_metadata(cls, value: object) -> object:
        return clean_document_metadata(value)


class UrlImportIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    folder: str = Field(default="", max_length=255)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("url", mode="before")
    @classmethod
    def clean_url(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if not cleaned.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return cleaned

    @field_validator("folder", mode="before")
    @classmethod
    def clean_folder(cls, value: object) -> object:
        return clean_document_folder(value)

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value: object) -> object:
        return clean_document_tags(value)


class DocumentFolderOut(BaseModel):
    folder: str
    count: int


class FolderRenameIn(BaseModel):
    from_folder: str = Field(min_length=1, max_length=255)
    to_folder: str = Field(min_length=1, max_length=255)

    @field_validator("from_folder", "to_folder", mode="before")
    @classmethod
    def clean_folder(cls, value: object) -> object:
        return clean_document_folder(value)


class FolderRenameOut(BaseModel):
    updated: int


class SiteImportIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    folder: str = Field(default="", max_length=255)
    tags: list[str] = Field(default_factory=list, max_length=20)
    max_pages: int = Field(default=10, ge=1, le=20)
    same_origin: bool = True

    @field_validator("url", mode="before")
    @classmethod
    def clean_url(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if not cleaned.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return cleaned

    @field_validator("folder", mode="before")
    @classmethod
    def clean_folder(cls, value: object) -> object:
        return clean_document_folder(value)

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value: object) -> object:
        return clean_document_tags(value)


class DocumentUploadOut(BaseModel):
    id: UUID
    status: str
    duplicate: bool = False


class SiteImportFailureOut(BaseModel):
    url: str
    code: str


class SiteImportOut(BaseModel):
    pages: int
    created: list[DocumentUploadOut] = Field(default_factory=list)
    duplicates: list[DocumentUploadOut] = Field(default_factory=list)
    failed: list[SiteImportFailureOut] = Field(default_factory=list)


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
    buckets: list[UsageByKeyBucketOut]


class ModelEvalQuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=5000)
    reference_answer: str = Field(default="", max_length=10000)
    scoring_criteria: str = Field(default="", max_length=5000)
    expected_keywords: list[str] = Field(default_factory=list, max_length=50)
    regex: str = Field(default="", max_length=500)


class ModelEvalQuestionOut(ModelEvalQuestionIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sort_order: int = 0


class ModelEvalDatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    questions: list[ModelEvalQuestionIn] = Field(default_factory=list, max_length=200)


class ModelEvalDatasetOut(BaseModel):
    id: UUID
    name: str
    description: str
    question_count: int = 0
    created_at: datetime


class ModelEvalDatasetDetail(ModelEvalDatasetOut):
    questions: list[ModelEvalQuestionOut] = Field(default_factory=list)


class ModelEvalRunCreate(BaseModel):
    dataset_id: UUID
    name: str = Field(default="", max_length=120)
    models: list[ArenaModelIn] = Field(min_length=1, max_length=10)
    parameters: GenerationSettings = Field(default_factory=GenerationSettings)
    concurrency: int = Field(default=3, ge=1, le=5)
    methods: list[Literal["rule", "ai"]] = Field(default_factory=lambda: ["rule"])
    judge_provider_id: str | None = Field(default=None, max_length=50)
    judge_model: str | None = Field(default=None, max_length=200)


class ModelEvalScoreOut(BaseModel):
    method: str
    score: float | None = None
    passed: bool | None = None
    reason: str = ""
    judge_provider_id: str | None = None
    judge_model: str | None = None


class ModelEvalItemOut(BaseModel):
    id: UUID
    question_id: UUID
    provider_id: str
    model: str
    question: str
    answer: str
    status: str
    error_code: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost: float = 0.0
    ttft_ms: float | None = None
    latency_ms: float | None = None
    scores: list[ModelEvalScoreOut] = Field(default_factory=list)


class ModelEvalRunOut(BaseModel):
    id: UUID
    dataset_id: UUID
    name: str
    status: str
    config: dict
    metrics: dict | None = None
    error_code: str | None = None
    progress_total: int
    progress_done: int
    progress_failed: int
    progress_running: int
    current_model: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class ModelEvalRunDetail(ModelEvalRunOut):
    items: list[ModelEvalItemOut] = Field(default_factory=list)


class ModelEvalManualScoreIn(BaseModel):
    score: float | None = Field(default=None, ge=0, le=5)
    passed: bool | None = None
    reason: str = Field(default="", max_length=1000)


class ArenaRoundCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    models: list[ArenaModelIn] = Field(min_length=2, max_length=4)
    generation_settings: GenerationSettings = Field(default_factory=GenerationSettings)
    blind: bool = False


class ArenaResponseOut(BaseModel):
    id: UUID
    position: int
    label: str
    provider_id: str | None = None
    model: str | None = None
    status: str
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost: float = 0.0
    ttft_ms: float | None = None
    total_ms: float | None = None
    error_code: str | None = None
    feedback: str | None = None
    attempt: int = 1


class ArenaRoundOut(BaseModel):
    id: UUID
    prompt: str
    blind: bool
    revealed: bool
    vote_response_id: UUID | None = None
    vote_reason: str = ""
    generation_settings: dict = Field(default_factory=dict)
    created_at: datetime
    responses: list[ArenaResponseOut] = Field(default_factory=list)


class ArenaVoteIn(BaseModel):
    response_id: UUID
    reason: str = Field(default="", max_length=500)


class ArenaFeedbackIn(BaseModel):
    feedback: Literal["helpful", "unhelpful"] | None = None


class ArenaRevealOut(BaseModel):
    responses: list[ArenaResponseOut]


class UsageRecentItemOut(BaseModel):
    id: UUID
    source: str
    provider_id: str | None
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int
    cost: float
    status: str | None
    conversation_id: UUID | None
    created_at: datetime = Field(default_factory=list)


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


class QuotaKnowledgeOut(BaseModel):
    max_kbs: int
    kb_count: int
    max_documents_per_kb: int
    max_kb_bytes: int
    kb_bytes: int


class QuotaMemoryOut(BaseModel):
    max_memories: int
    memory_count: int


class QuotaSummaryOut(BaseModel):
    plan: str
    requests: QuotaWindowOut
    tokens: QuotaWindowOut
    max_keys: int
    active_keys: int
    knowledge: QuotaKnowledgeOut
    memory: QuotaMemoryOut


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


class FileOut(BaseModel):
    id: UUID
    filename: str
    mime: str
    size_bytes: int
    status: str
    error_code: str | None
    page_count: int | None
    kb_id: UUID
    kb_name: str
    created_at: datetime


class DashboardCountsOut(BaseModel):
    providers: int
    models: int
    conversations: int
    projects: int
    knowledge_bases: int
    agents: int
    plugins: int
    unread_notifications: int
    requests_30d: int
    tokens_30d: int
    cost_30d: float


class DashboardRecentProjectOut(BaseModel):
    id: UUID
    name: str
    updated_at: datetime


class DashboardOut(BaseModel):
    counts: DashboardCountsOut
    recent_conversations: list[ConversationOut] = Field(default_factory=list)
    recent_projects: list[DashboardRecentProjectOut] = Field(default_factory=list)


class SearchResultOut(BaseModel):
    type: str
    id: str
    title: str
    subtitle: str
    href: str


class SearchOut(BaseModel):
    query: str
    results: list[SearchResultOut] = Field(default_factory=list)
