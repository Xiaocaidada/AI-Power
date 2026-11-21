from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


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


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[Literal["chat:write", "kb:read"]] | None = None
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
