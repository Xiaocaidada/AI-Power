"""Capability defaults and conservative inference for synced provider models.

Provider ``/models`` responses do not publish tool/vision support, so a synced
model would otherwise be stuck with ``chat`` + ``stream`` forever. We infer
only well-known tool-calling families and let an explicit manual capability
edit (``source="manual"``) override the inference.
"""

from __future__ import annotations

DEFAULT_CAPABILITIES: tuple[str, ...] = ("chat", "stream")

# Model families that publicly support OpenAI-style function/tool calling.
_TOOL_CAPABLE_PREFIXES: tuple[str, ...] = (
    "glm-4",  # Zhipu GLM-4 / GLM-4.5 / GLM-4.6 / GLM-4-Air / GLM-4-Plus / GLM-4-Flash
    "glm-5",  # Zhipu GLM-5 / GLM-5.x / GLM-5-Turbo
    "gpt-3.5-turbo",
    "gpt-4",
    "gpt-5",
    "o1",
    "o3",
    "o4",
    "deepseek-chat",
    "qwen2.5",
    "qwen3",
    "qwen-max",
    "qwen-plus",
    "qwen-turbo",
    "claude",
    "gemini",
    "mistral-large",
    "mistral-small",
    "command-r",
)


def supports_tools_by_name(model_id: str) -> bool:
    name = (model_id or "").strip().lower()
    candidates = {
        name,
        name.rsplit("/", 1)[-1],
        name.rsplit(":", 1)[-1],
    }
    return any(
        candidate.startswith(prefix)
        for candidate in candidates
        for prefix in _TOOL_CAPABLE_PREFIXES
    )


def effective_capabilities(
    model_id: str,
    declared: list[str] | None,
    source: str,
) -> list[str]:
    """Return declared capabilities plus safe inference for synced models."""
    capabilities = list(declared or DEFAULT_CAPABILITIES)
    if source == "synced" and supports_tools_by_name(model_id):
        capabilities = sorted({*capabilities, "tools"})
    return capabilities
