from types import SimpleNamespace

import app.deps as deps
import app.providers.registry as registry_module
from app.providers.registry import ProviderRegistry, build_registry


def _settings(**overrides) -> SimpleNamespace:
    values = {
        "deepseek_api_key": "",
        "deepseek_base_url": "https://api.deepseek.com",
        "local_llm_base_url": "",
        "local_llm_api_key": "",
        "provider_timeout_seconds": 1.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_build_registry_includes_configured_providers(monkeypatch):
    monkeypatch.setattr(
        registry_module,
        "get_settings",
        lambda: _settings(deepseek_api_key="k", local_llm_base_url="http://local/v1"),
    )

    registry = build_registry()

    assert {provider.id for provider in registry.all()} == {"deepseek", "local-qwen"}


def test_build_registry_omits_unconfigured_providers(monkeypatch):
    monkeypatch.setattr(registry_module, "get_settings", lambda: _settings())

    registry = build_registry()

    assert registry.all() == []


def test_get_registry_is_lazy_and_cached(monkeypatch):
    calls: list[int] = []

    def fake_build() -> ProviderRegistry:
        calls.append(1)
        return ProviderRegistry({})

    monkeypatch.setattr(deps, "build_registry", fake_build)
    monkeypatch.setattr(deps, "_registry", None)

    first = deps.get_registry()
    second = deps.get_registry()

    assert first is second
    assert len(calls) == 1
