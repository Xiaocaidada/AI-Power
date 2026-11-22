from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid6 import uuid7

from app.vector import EmbeddingVector


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(120))
    plan: Mapped[str] = mapped_column(String(20), default="free")
    is_personal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (PrimaryKeyConstraint("workspace_id", "user_id"),)


class ModelCatalog(Base):
    __tablename__ = "model_catalog"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    provider_id: Mapped[str] = mapped_column(String(50), index=True)
    model_id: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(200))
    context_window: Mapped[int] = mapped_column(Integer, default=0)
    input_price: Mapped[float] = mapped_column(default=0.0)
    output_price: Mapped[float] = mapped_column(default=0.0)
    tags: Mapped[str] = mapped_column(String(300), default="")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("provider_id", "model_id", name="uq_model_catalog_provider_model"),
    )


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    category: Mapped[str] = mapped_column(String(50), default="general", index=True)
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class PromptFavorite(Base):
    __tablename__ = "prompt_favorites"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("template_id", "user_id", name="uq_prompt_favorites_template_user"),
    )


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    system_prompt: Mapped[str] = mapped_column(Text)
    variables: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_prompt_versions_template_version"),
    )


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workflow_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_version"),
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workflow_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[UUID] = mapped_column(ForeignKey("workflow_versions.id", ondelete="CASCADE"))
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    api_key_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), default=None
    )
    kb_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"), default=None
    )
    status: Mapped[str] = mapped_column(String(20), default="running")
    input_text: Mapped[str] = mapped_column(Text, default="")
    error_code: Mapped[str | None] = mapped_column(String(50), default=None)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_ms: Mapped[float | None] = mapped_column(Float, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (Index("ix_workflow_runs_workspace_started", "workspace_id", "started_at"),)


class WorkflowRunEvent(Base):
    __tablename__ = "workflow_run_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_workflow_run_events_run_seq"),
        Index("ix_workflow_run_events_run_seq", "run_id", "seq"),
    )


class WorkflowNodeRun(Base):
    __tablename__ = "workflow_node_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    node_id: Mapped[str] = mapped_column(String(80))
    node_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="running")
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    input_summary: Mapped[str] = mapped_column(String(500), default="")
    output_summary: Mapped[str] = mapped_column(String(500), default="")
    error_code: Mapped[str | None] = mapped_column(String(50), default=None)
    duration_ms: Mapped[float | None] = mapped_column(Float, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CollaborationRun(Base):
    __tablename__ = "collaboration_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    api_key_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), default=None
    )
    provider_id: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(200))
    kb_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"), default=None
    )
    status: Mapped[str] = mapped_column(String(20), default="running")
    input_text: Mapped[str] = mapped_column(Text, default="")
    plan: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, default=None)
    final_output: Mapped[str] = mapped_column(Text, default="")
    rounds: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(50), default=None)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_ms: Mapped[float | None] = mapped_column(Float, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class CollaborationRunEvent(Base):
    __tablename__ = "collaboration_run_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("collaboration_runs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_collaboration_run_events_run_seq"),
        Index("ix_collaboration_run_events_run_seq", "run_id", "seq"),
    )


class CollaborationStep(Base):
    __tablename__ = "collaboration_steps"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("collaboration_runs.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    step_key: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="running")
    input_summary: Mapped[str] = mapped_column(String(500), default="")
    output_summary: Mapped[str] = mapped_column(String(500), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    error_code: Mapped[str | None] = mapped_column(String(50), default=None)
    duration_ms: Mapped[float | None] = mapped_column(Float, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    settings: Mapped[dict[str, object] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    replaced_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CustomAgent(Base):
    __tablename__ = "custom_agents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    instructions: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), default="general", index=True)
    default_provider_id: Mapped[str | None] = mapped_column(String(50), default=None)
    default_model: Mapped[str | None] = mapped_column(String(200), default=None)
    default_kb_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"), default=None
    )
    tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    plugin_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    visibility: Mapped[str] = mapped_column(String(20), default="private", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_custom_agents_workspace_name"),
        Index("ix_custom_agents_workspace_archived", "workspace_id", "archived_at"),
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    default_provider_id: Mapped[str | None] = mapped_column(String(50), default=None)
    default_model: Mapped[str | None] = mapped_column(String(200), default=None)
    default_kb_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"), default=None
    )
    default_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (Index("ix_projects_workspace_archived", "workspace_id", "archived_at"),)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), default=None, index=True
    )
    custom_agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("custom_agents.id", ondelete="SET NULL"), default=None, index=True
    )
    title: Mapped[str] = mapped_column(String(120), default="")
    provider_id: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(200))
    kb_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"), default=None
    )
    prompt_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"), default=None
    )
    system_prompt: Mapped[str | None] = mapped_column(Text, default=None)
    agent: Mapped[bool] = mapped_column(Boolean, default=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    generation_settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (
        Index(
            "ix_conversations_workspace_project_archived",
            "workspace_id",
            "project_id",
            "archived_at",
        ),
        Index("ix_conversations_workspace_pinned", "workspace_id", "pinned"),
    )


class ChatAttachment(Base):
    __tablename__ = "chat_attachments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), default=None, index=True
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), default=None, index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(20), default="document")
    status: Mapped[str] = mapped_column(String(20), default="ready")
    error_code: Mapped[str | None] = mapped_column(String(50), default=None)
    extracted_text: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (
        Index(
            "ix_chat_attachments_workspace_conversation",
            "workspace_id",
            "conversation_id",
        ),
    )


class ConversationKnowledgeBase(Base):
    __tablename__ = "conversation_knowledge_bases"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    kb_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "kb_id", name="uq_conversation_knowledge_bases_pair"
        ),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="completed")
    provider_id: Mapped[str | None] = mapped_column(String(50), default=None)
    model: Mapped[str | None] = mapped_column(String(200), default=None)
    prompt_tokens: Mapped[int | None] = mapped_column(default=None)
    completion_tokens: Mapped[int | None] = mapped_column(default=None)
    request_id: Mapped[str | None] = mapped_column(String(64), default=None)
    reply_to_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MessageFeedback(Base):
    __tablename__ = "message_feedback"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rating: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_message_feedback_message_user"),
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[str] = mapped_column(String(200), default="chat:write,kb:read")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer, default=None)


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    provider_type: Mapped[str] = mapped_column(String(30), default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String(500))
    api_key_encrypted: Mapped[str] = mapped_column(String(1000))
    api_key_hint: Mapped[str] = mapped_column(String(20), default="")
    note: Mapped[str] = mapped_column(String(500), default="")
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    last_error: Mapped[str | None] = mapped_column(String(200), default=None)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (Index("ix_provider_configs_workspace_deleted", "workspace_id", "deleted_at"),)


class ProviderModel(Base):
    __tablename__ = "provider_models"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    config_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_configs.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(200), default="")
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("config_id", "model_id", name="uq_provider_models_config_model"),
    )


class MarketModel(Base):
    __tablename__ = "market_models"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    provider_id: Mapped[str] = mapped_column(String(100), index=True)
    provider_name: Mapped[str] = mapped_column(String(100))
    model_id: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(50), default="general", index=True)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    input_types: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["text"])
    output_types: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["text"])
    context_window: Mapped[int] = mapped_column(Integer, default=0)
    max_output: Mapped[int | None] = mapped_column(Integer, default=None)
    logo_url: Mapped[str] = mapped_column(String(500), default="")
    docs_url: Mapped[str] = mapped_column(String(500), default="")
    featured: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("provider_id", "model_id", name="uq_market_models_provider_model"),
    )


class HomePlacement(Base):
    __tablename__ = "home_placements"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    kind: Mapped[str] = mapped_column(String(20), default="banner", index=True)
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(String(500), default="")
    link_url: Mapped[str] = mapped_column(String(500), default="")
    link_label: Mapped[str] = mapped_column(String(50), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (Index("ix_home_placements_kind_enabled", "kind", "enabled"),)


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text)
    cover_url: Mapped[str] = mapped_column(String(500), default="")
    category: Mapped[str] = mapped_column(String(30), default="notice", index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (Index("ix_announcements_status_published", "status", "published_at"),)


class AnnouncementRead(Base):
    __tablename__ = "announcement_reads"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    announcement_id: Mapped[UUID] = mapped_column(
        ForeignKey("announcements.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "announcement_id", "user_id", name="uq_announcement_reads_announcement_user"
        ),
        Index("ix_announcement_reads_user_read", "user_id", "read_at"),
    )


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), default=None, index=True
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), unique=True, index=True, default=None
    )
    source: Mapped[str] = mapped_column(String(20), default="chat", index=True)
    api_key_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), default=None, index=True
    )
    workflow_node_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_node_runs.id", ondelete="SET NULL"),
        unique=True,
        index=True,
        default=None,
    )
    collaboration_step_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("collaboration_steps.id", ondelete="SET NULL"),
        unique=True,
        index=True,
        default=None,
    )
    provider_id: Mapped[str | None] = mapped_column(String(50), default=None)
    model: Mapped[str | None] = mapped_column(String(200), default=None)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    input_price: Mapped[float | None] = mapped_column(Float, default=None)
    output_price: Mapped[float | None] = mapped_column(Float, default=None)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    unpriced: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_usage_events_workspace_created", "workspace_id", "created_at"),
        Index("ix_usage_events_workspace_source_created", "workspace_id", "source", "created_at"),
        Index(
            "ix_usage_events_workspace_api_key_created", "workspace_id", "api_key_id", "created_at"
        ),
    )


class MessageCitation(Base):
    __tablename__ = "message_citations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    citation_index: Mapped[int] = mapped_column(Integer)
    document_id: Mapped[UUID] = mapped_column(default=uuid7)
    chunk_id: Mapped[UUID] = mapped_column(default=uuid7)
    page_no: Mapped[int | None] = mapped_column(Integer, default=None)
    snippet: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("message_id", "citation_index", name="uq_message_citations_message_index"),
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    kb_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    error_code: Mapped[str | None] = mapped_column(String(50), default=None)
    page_count: Mapped[int | None] = mapped_column(Integer, default=None)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (
        Index(
            "uq_documents_workspace_kb_hash",
            "workspace_id",
            "kb_id",
            "content_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kb_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    page_no: Mapped[int | None] = mapped_column(Integer, default=None)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(EmbeddingVector(1024))


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(500), default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (Index("ix_ingestion_jobs_status", "status"),)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    action: Mapped[str] = mapped_column(String(50))
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(64), default=None)
    detail: Mapped[dict[str, object] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), default=None
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), unique=True, default=None
    )
    provider_id: Mapped[str | None] = mapped_column(String(50), default=None)
    model: Mapped[str | None] = mapped_column(String(200), default=None)
    retrieval_ms: Mapped[float | None] = mapped_column(Float, default=None)
    ttft_ms: Mapped[float | None] = mapped_column(Float, default=None)
    total_ms: Mapped[float | None] = mapped_column(Float, default=None)
    status: Mapped[str] = mapped_column(String(20), default="streaming")
    error_code: Mapped[str | None] = mapped_column(String(50), default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    agents: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (Index("ix_traces_workspace_created", "workspace_id", "created_at"),)


class EvalDataset(Base):
    __tablename__ = "eval_datasets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class EvalQuestion(Base):
    __tablename__ = "eval_questions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("eval_datasets.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    relevant_document_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("eval_datasets.id", ondelete="CASCADE"), index=True
    )
    kb_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    config: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, object] | None] = mapped_column(JSON, default=None)
    error_code: Mapped[str | None] = mapped_column(String(50), default=None)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_eval_runs_workspace_created", "workspace_id", "created_at"),)


class EvalRunItem(Base):
    __tablename__ = "eval_run_items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("eval_questions.id", ondelete="CASCADE"), index=True
    )
    question_text: Mapped[str] = mapped_column(Text)
    hit_rank: Mapped[int | None] = mapped_column(Integer, default=None)
    reciprocal_rank: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_hit: Mapped[bool | None] = mapped_column(Boolean, default=None)
    latency_ms: Mapped[float | None] = mapped_column(Float, default=None)
    top_document_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    top_chunk_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    answer: Mapped[str | None] = mapped_column(Text, default=None)
    judge_score: Mapped[int | None] = mapped_column(Integer, default=None)
    judge_faithful: Mapped[bool | None] = mapped_column(Boolean, default=None)
    judge_reason: Mapped[str | None] = mapped_column(String(1000), default=None)
    judge_error: Mapped[str | None] = mapped_column(String(100), default=None)
    answer_latency_ms: Mapped[float | None] = mapped_column(Float, default=None)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    error_code: Mapped[str | None] = mapped_column(String(50), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "question_id", name="uq_eval_run_items_run_question"),
    )


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(1000))
    secret_encrypted: Mapped[str] = mapped_column(String(1000))
    events: Mapped[str] = mapped_column(String(500), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    webhook_id: Mapped[UUID] = mapped_column(
        ForeignKey("webhooks.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_status: Mapped[int | None] = mapped_column(Integer, default=None)
    error: Mapped[str | None] = mapped_column(String(500), default=None)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (
        Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),
        Index("ix_webhook_deliveries_workspace_created", "workspace_id", "created_at"),
    )


class PluginDefinition(Base):
    __tablename__ = "plugin_definitions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    category: Mapped[str] = mapped_column(String(40), default="general", index=True)
    docs_url: Mapped[str] = mapped_column(String(500), default="")
    endpoint_url: Mapped[str] = mapped_column(String(1000))
    method: Mapped[str] = mapped_column(String(10), default="POST")
    auth_type: Mapped[str] = mapped_column(String(20), default="none")
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PluginConfig(Base):
    __tablename__ = "plugin_configs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    plugin_id: Mapped[UUID] = mapped_column(
        ForeignKey("plugin_definitions.id", ondelete="CASCADE"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    credential_encrypted: Mapped[str] = mapped_column(String(1000), default="")
    credential_hint: Mapped[str] = mapped_column(String(20), default="")
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    last_error: Mapped[str | None] = mapped_column(String(200), default=None)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "plugin_id", name="uq_plugin_configs_workspace_plugin"),
    )


class ConversationPlugin(Base):
    __tablename__ = "conversation_plugins"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    plugin_id: Mapped[UUID] = mapped_column(
        ForeignKey("plugin_definitions.id", ondelete="CASCADE"), index=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "plugin_id", name="uq_conversation_plugins_conversation_plugin"
        ),
    )


class PluginCall(Base):
    __tablename__ = "plugin_calls"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), default=None, index=True
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), default=None
    )
    plugin_id: Mapped[UUID] = mapped_column(
        ForeignKey("plugin_definitions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="ok", index=True)
    request_summary: Mapped[str] = mapped_column(String(500), default="")
    response_summary: Mapped[str] = mapped_column(String(500), default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(50), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_plugin_calls_workspace_created", "workspace_id", "created_at"),
        Index("ix_plugin_calls_conversation_created", "conversation_id", "created_at"),
    )
