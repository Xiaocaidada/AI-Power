from app.config import get_settings
from app.providers.base import LLMProvider, ProviderNotFoundError
from app.providers.openai_compat import OpenAICompatProvider


class ProviderRegistry:
    def __init__(self, providers: dict[str, LLMProvider] | None = None) -> None:
        self._providers = dict(providers or {})

    def get(self, provider_id: str) -> LLMProvider:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ProviderNotFoundError(provider_id)
        return provider

    def all(self) -> list[LLMProvider]:
        return list(self._providers.values())


def build_registry() -> ProviderRegistry:
    settings = get_settings()
    providers: dict[str, LLMProvider] = {}

    if settings.deepseek_api_key:
        providers["deepseek"] = OpenAICompatProvider(
            "deepseek",
            settings.deepseek_base_url,
            settings.deepseek_api_key,
            timeout=settings.provider_timeout_seconds,
        )
    if settings.local_llm_base_url:
        providers["local-qwen"] = OpenAICompatProvider(
            "local-qwen",
            settings.local_llm_base_url,
            settings.local_llm_api_key,
            timeout=settings.provider_timeout_seconds,
        )
    return ProviderRegistry(providers)
