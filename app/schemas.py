from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


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


class ConversationCreate(BaseModel):
    provider_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=200)
    kb_id: UUID | None = None

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
    created_at: datetime


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
