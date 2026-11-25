from dataclasses import dataclass

from app.services.context_budget import (
    DEFAULT_HISTORY_LIMIT,
    rag_char_limit,
    trim_history,
)


@dataclass
class _Message:
    content: str


def _messages(count: int, text: str = "hello") -> list[_Message]:
    return [_Message(content=f"{text}-{index}") for index in range(count)]


def test_unknown_context_keeps_legacy_message_limit():
    messages = _messages(20)

    assert len(trim_history(messages, 0, None)) == DEFAULT_HISTORY_LIMIT


def test_large_context_keeps_more_than_twelve_messages():
    messages = _messages(20)

    kept = trim_history(messages, 128000, 4096)

    assert len(kept) == 20
    assert kept[-1].content == "hello-19"


def test_small_context_trims_old_messages():
    messages = _messages(20, "x" * 5000)

    kept = trim_history(messages, 4096, 2048)

    assert len(kept) == 1
    assert kept[0].content.endswith("19")


def test_rag_limit_shrinks_for_small_context():
    assert rag_char_limit(0, None, 0, 6000) == 6000
    assert rag_char_limit(4096, 2048, 1000, 6000) == 800
    assert rag_char_limit(128000, 4096, 1000, 6000) == 6000
