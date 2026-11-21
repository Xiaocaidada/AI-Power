from app.config import get_settings
from app.providers.embedding import OpenAICompatEmbeddingProvider


def build_embedder() -> OpenAICompatEmbeddingProvider:
    settings = get_settings()
    return OpenAICompatEmbeddingProvider(
        settings.embedding_base_url,
        settings.embedding_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dim,
        timeout=settings.provider_timeout_seconds,
    )
