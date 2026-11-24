"""Shared generation-setting normalization for conversations, Agents and runs."""

from typing import Any

GENERATION_LIMITS: dict[str, tuple[float, float]] = {
    "temperature": (0.0, 2.0),
    "max_tokens": (1, 32768),
    "top_p": (0.0, 1.0),
}


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def normalize_generation_settings(
    values: dict[str, object] | None,
) -> dict[str, object]:
    raw = values or {}
    settings: dict[str, object] = {}
    temperature = _number(raw.get("temperature"))
    if temperature is not None:
        settings["temperature"] = max(0.0, min(2.0, temperature))
    max_tokens = _number(raw.get("max_tokens"))
    if max_tokens is not None:
        settings["max_tokens"] = max(1, min(32768, int(max_tokens)))
    top_p = _number(raw.get("top_p"))
    if top_p is not None:
        settings["top_p"] = max(0.0, min(1.0, top_p))
    return settings


def generation_opts(values: dict[str, object] | None) -> dict[str, Any]:
    """Return only values accepted by provider ``stream_chat`` keyword arguments."""
    return dict(normalize_generation_settings(values))