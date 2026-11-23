import asyncio
import json
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from uuid import UUID

from uuid6 import uuid7

from app.db import SessionLocal
from app.providers.base import ChatMessage, LLMProvider, ProviderError
from app.services.usage_ledger import write_usage_event


@dataclass
class StreamMetrics:
    content: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost: float = 0.0
    unpriced: bool = True
    ttft_ms: float | None = None
    total_ms: float | None = None
    status: str = "completed"
    error_code: str | None = None


@dataclass
class CompletionMetrics:
    content: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost: float = 0.0
    unpriced: bool = True
    total_ms: float | None = None
    status: str = "completed"
    error_code: str | None = None


async def _record_usage(
    *,
    workspace_id: UUID,
    user_id: UUID,
    source: str,
    provider_id: str | None,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> tuple[float, bool] | None:
    async with SessionLocal() as session:
        written = await write_usage_event(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            source=source,
            provider_id=provider_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            source_ref_id=uuid7(),
        )
        await session.commit()
    if written is None:
        return None
    return float(written.cost or 0.0), bool(written.unpriced)


class ModelStream:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        messages: Sequence[ChatMessage],
        opts: dict[str, object],
        workspace_id: UUID,
        user_id: UUID,
        source: str,
    ) -> None:
        self.provider = provider
        self.model = model
        self.messages = list(messages)
        self.opts = opts
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.source = source
        self.metrics = StreamMetrics()

    async def events(self) -> AsyncIterator[tuple[str, dict[str, object]]]:
        started = time.perf_counter()
        first_token: float | None = None
        usage_seen = False
        try:
            async for chunk in self.provider.stream_chat(
                self.messages, self.model, **self.opts
            ):
                if chunk.delta:
                    if first_token is None:
                        first_token = time.perf_counter()
                        self.metrics.ttft_ms = round((first_token - started) * 1000, 1)
                    self.metrics.content += chunk.delta
                    yield "delta", {"text": chunk.delta}
                if chunk.usage is not None:
                    usage_seen = True
                    self.metrics.prompt_tokens = chunk.usage.prompt_tokens
                    self.metrics.completion_tokens = chunk.usage.completion_tokens
            self.metrics.total_ms = round((time.perf_counter() - started) * 1000, 1)
            if self.metrics.ttft_ms is None:
                self.metrics.ttft_ms = self.metrics.total_ms
            recorded = None
            if usage_seen:
                recorded = await _record_usage(
                    workspace_id=self.workspace_id,
                    user_id=self.user_id,
                    source=self.source,
                    provider_id=getattr(self.provider, "id", None),
                    model=self.model,
                    prompt_tokens=self.metrics.prompt_tokens,
                    completion_tokens=self.metrics.completion_tokens,
                )
            if recorded is not None:
                self.metrics.cost, self.metrics.unpriced = recorded
            yield "usage", {
                "prompt_tokens": self.metrics.prompt_tokens,
                "completion_tokens": self.metrics.completion_tokens,
                "cost": self.metrics.cost,
                "estimated": self.metrics.unpriced,
            }
            yield "done", {
                "ttft_ms": self.metrics.ttft_ms,
                "total_ms": self.metrics.total_ms,
                "prompt_tokens": self.metrics.prompt_tokens,
                "completion_tokens": self.metrics.completion_tokens,
                "cost": self.metrics.cost,
                "estimated": self.metrics.unpriced,
            }
        except asyncio.CancelledError:
            self.metrics.status = "cancelled"
            self.metrics.total_ms = round((time.perf_counter() - started) * 1000, 1)
            raise
        except ProviderError as exc:
            self.metrics.status = "failed"
            self.metrics.error_code = exc.code
            self.metrics.total_ms = round((time.perf_counter() - started) * 1000, 1)
            yield "error", {"code": exc.code, "message": exc.message}
        except Exception:
            self.metrics.status = "failed"
            self.metrics.error_code = "internal_error"
            self.metrics.total_ms = round((time.perf_counter() - started) * 1000, 1)
            yield "error", {"code": "internal_error", "message": "Model call failed"}


class ModelCompletion:
    """Run one non-streaming completion for server-side batch work."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        messages: Sequence[ChatMessage],
        opts: dict[str, object],
        workspace_id: UUID,
        user_id: UUID,
        source: str,
    ) -> None:
        self.provider = provider
        self.model = model
        self.messages = list(messages)
        self.opts = opts
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.source = source
        self.metrics = CompletionMetrics()

    async def run(self) -> CompletionMetrics:
        started = time.perf_counter()
        usage_seen = False
        try:
            complete = getattr(self.provider, "complete", None)
            if complete is None:
                result_content = ""
                usage = None
                async for chunk in self.provider.stream_chat(
                    self.messages, self.model, **self.opts
                ):
                    result_content += chunk.delta
                    if chunk.usage is not None:
                        usage = chunk.usage
                self.metrics.content = result_content
                if usage is not None:
                    usage_seen = True
                    self.metrics.prompt_tokens = usage.prompt_tokens
                    self.metrics.completion_tokens = usage.completion_tokens
            else:
                result = await complete(self.messages, self.model, **self.opts)
                self.metrics.content = result.content
                if result.usage is not None:
                    usage_seen = True
                    self.metrics.prompt_tokens = result.usage.prompt_tokens
                    self.metrics.completion_tokens = result.usage.completion_tokens
        except ProviderError as exc:
            self.metrics.status = "failed"
            self.metrics.error_code = exc.code
            self.metrics.total_ms = round((time.perf_counter() - started) * 1000, 1)
            return self.metrics
        except Exception:
            self.metrics.status = "failed"
            self.metrics.error_code = "internal_error"
            self.metrics.total_ms = round((time.perf_counter() - started) * 1000, 1)
            return self.metrics

        self.metrics.total_ms = round((time.perf_counter() - started) * 1000, 1)
        if usage_seen:
            recorded = await _record_usage(
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                source=self.source,
                provider_id=getattr(self.provider, "id", None),
                model=self.model,
                prompt_tokens=self.metrics.prompt_tokens,
                completion_tokens=self.metrics.completion_tokens,
            )
            if recorded is not None:
                self.metrics.cost, self.metrics.unpriced = recorded
        return self.metrics


def sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"