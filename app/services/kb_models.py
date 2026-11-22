import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ProviderConfig
from app.providers.base import ProviderError
from app.providers.embedding import OpenAICompatEmbeddingProvider
from app.providers.rerank import HttpReranker, Reranker, build_reranker
from app.services.embedding_factory import build_embedder
from app.services.knowledge_settings import KnowledgeBaseSettings
from app.services.provider_secrets import decrypt_api_key

logger = logging.getLogger(__name__)


def _can_use(config: ProviderConfig, kb: Any) -> bool:
    return (
        config.deleted_at is None
        and config.workspace_id == kb.workspace_id
        and (config.owner_user_id == kb.user_id or config.shared)
    )


async def build_kb_embedder(session: AsyncSession, kb: Any, kb_settings: KnowledgeBaseSettings):
    selection = kb_settings.embedding
    if selection.provider_config_id is None:
        return build_embedder()
    config = await session.get(ProviderConfig, selection.provider_config_id)
    if config is None or not _can_use(config, kb):
        raise ProviderError(
            "embedding_config_unavailable",
            "Embedding provider config is not available for this knowledge base",
        )
    if not selection.model:
        raise ProviderError("embedding_model_required", "Embedding model is required")
    return OpenAICompatEmbeddingProvider(
        config.base_url,
        decrypt_api_key(config.api_key_encrypted),
        model=selection.model,
        dimensions=selection.dimensions,
        timeout=get_settings().provider_timeout_seconds,
    )


async def build_kb_reranker(
    session: AsyncSession, kb: Any, kb_settings: KnowledgeBaseSettings
) -> Reranker | None:
    selection = kb_settings.rerank
    if selection.provider_config_id is None:
        return build_reranker()
    config = await session.get(ProviderConfig, selection.provider_config_id)
    if config is None or not _can_use(config, kb) or not selection.model:
        logger.warning("rerank provider config unavailable; disabling rerank")
        return None
    try:
        api_key = decrypt_api_key(config.api_key_encrypted)
    except ValueError:
        logger.warning("rerank provider key cannot be decrypted; disabling rerank")
        return None
    return HttpReranker(
        base_url=config.base_url,
        model=selection.model,
        timeout=get_settings().rerank_timeout_seconds,
        api_key=api_key,
    )
