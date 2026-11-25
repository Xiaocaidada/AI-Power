"""Approximate, model-configured context budgeting.

Providers do not publish tokenizers, so we use a conservative character-based
estimate: roughly two characters per token for mixed Chinese/English text.
The configured context window is authoritative; ``0`` keeps the legacy fixed
12-message policy.
"""

from __future__ import annotations

from math import ceil

DEFAULT_HISTORY_LIMIT = 12
MAX_HISTORY_MESSAGES = 60
DEFAULT_OUTPUT_RESERVE = 2048
TOKEN_SAFETY_MARGIN = 512
MIN_INPUT_TOKENS = 512
MIN_RAG_CHARS = 800
TOKENS_TO_CHARS = 2


def estimate_tokens(content: object) -> int:
    if isinstance(content, str):
        return max(1, ceil(len(content) / TOKENS_TO_CHARS))
    if isinstance(content, list):
        chars = 0
        images = 0
        for part in content:
            if not isinstance(part, dict):
                continue
            if isinstance(part.get("text"), str):
                chars += len(part["text"])
            if part.get("type") == "image_url":
                images += 1
        # Vision models typically bill an image as tens to hundreds of tokens.
        return max(1, ceil(chars / TOKENS_TO_CHARS) + images * 256)
    return 1


def message_tokens(message: object) -> int:
    return estimate_tokens(getattr(message, "content", ""))


def output_reserve(max_output: int | None, configured_max_tokens: object = None) -> int:
    configured = configured_max_tokens if isinstance(configured_max_tokens, int) else 0
    return max(max_output or 0, configured, DEFAULT_OUTPUT_RESERVE)


def trim_history[MessageT](
    messages: list[MessageT],
    context_window: int,
    max_output: int | None,
    *,
    configured_max_tokens: object = None,
) -> list[MessageT]:
    if not messages:
        return []
    if context_window <= 0:
        return messages[-DEFAULT_HISTORY_LIMIT:]

    budget = max(
        MIN_INPUT_TOKENS,
        context_window - output_reserve(max_output, configured_max_tokens) - TOKEN_SAFETY_MARGIN,
    )
    candidates = messages[-MAX_HISTORY_MESSAGES:]
    kept: list[MessageT] = []
    used = 0
    for message in reversed(candidates):
        tokens = message_tokens(message)
        if kept and used + tokens > budget:
            break
        kept.append(message)
        used += tokens
    return list(reversed(kept))


def rag_char_limit(
    context_window: int,
    max_output: int | None,
    history_tokens: int,
    configured_chars: int,
    *,
    configured_max_tokens: object = None,
) -> int:
    if context_window <= 0:
        return configured_chars
    budget = max(
        MIN_INPUT_TOKENS,
        context_window - output_reserve(max_output, configured_max_tokens) - TOKEN_SAFETY_MARGIN,
    )
    remaining_tokens = max(
        MIN_INPUT_TOKENS // 2,
        budget - history_tokens - TOKEN_SAFETY_MARGIN,
    )
    return min(
        configured_chars,
        max(MIN_RAG_CHARS, remaining_tokens * TOKENS_TO_CHARS),
    )
