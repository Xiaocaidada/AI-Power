from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

Role = Literal["system", "user", "assistant"]
MessageContent = str | list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: MessageContent


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    provider_id: str


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ChatChunk:
    delta: str = ""
    usage: Usage | None = None
    finish_reason: str | None = None


class ProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProviderNotFoundError(ProviderError):
    def __init__(self, provider_id: str) -> None:
        super().__init__("provider_not_found", f"Unknown provider: {provider_id}")


class LLMProvider(Protocol):
    id: str

    async def list_models(self) -> list[ModelInfo]: ...

    def stream_chat(
        self, messages: list[ChatMessage], model: str, **opts: object
    ) -> AsyncIterator[ChatChunk]: ...
