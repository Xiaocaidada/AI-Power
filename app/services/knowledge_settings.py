import logging
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class ChunkingSettings(BaseModel):
    chunk_size: int = Field(default=1000, ge=50, le=4000)
    chunk_overlap: int = Field(default=150, ge=0, le=1000)

    @model_validator(mode="after")
    def _overlap_is_smaller(self) -> "ChunkingSettings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class RetrievalSettings(BaseModel):
    top_k: int = Field(default=5, ge=1, le=20)
    candidate_k: int = Field(default=20, ge=1, le=100)
    hybrid_enabled: bool = True
    rerank_enabled: bool = True

    @model_validator(mode="after")
    def _candidates_cover_top_k(self) -> "RetrievalSettings":
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be >= top_k")
        return self


class EmbeddingSelection(BaseModel):
    provider_config_id: UUID | None = None
    model: str | None = None
    dimensions: int = Field(default=1024, ge=1, le=4096)


class RerankSelection(BaseModel):
    provider_config_id: UUID | None = None
    model: str | None = None


class KnowledgeBaseSettings(BaseModel):
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    embedding: EmbeddingSelection = Field(default_factory=EmbeddingSelection)
    rerank: RerankSelection = Field(default_factory=RerankSelection)


def default_settings(settings: Settings | None = None) -> KnowledgeBaseSettings:
    current = settings or get_settings()
    return KnowledgeBaseSettings(
        chunking=ChunkingSettings(
            chunk_size=current.chunk_max_chars,
            chunk_overlap=current.chunk_overlap_chars,
        ),
        retrieval=RetrievalSettings(
            top_k=current.retrieval_top_k,
            candidate_k=current.retrieval_candidate_k,
            hybrid_enabled=current.retrieval_hybrid_enabled,
            rerank_enabled=current.rerank_enabled and bool(current.rerank_base_url.strip()),
        ),
        embedding=EmbeddingSelection(
            model=current.embedding_model,
            dimensions=current.embedding_dim,
        ),
        rerank=RerankSelection(model=current.rerank_model),
    )


def resolve_settings(
    raw: dict[str, Any] | None, settings: Settings | None = None
) -> KnowledgeBaseSettings:
    defaults = default_settings(settings).model_dump()
    if not raw:
        return KnowledgeBaseSettings.model_validate(defaults)
    try:
        return KnowledgeBaseSettings.model_validate(_merge(defaults, raw))
    except ValidationError:
        logger.warning("invalid knowledge base settings; falling back to defaults")
        return KnowledgeBaseSettings.model_validate(defaults)


def resolve_kb_settings(kb: Any, settings: Settings | None = None) -> KnowledgeBaseSettings:
    return resolve_settings(getattr(kb, "settings", None), settings)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged
