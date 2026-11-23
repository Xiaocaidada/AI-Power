import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.providers.base import (
    ChatChunk,
    ChatMessage,
    CompletionResult,
    ModelInfo,
    ProviderError,
    Usage,
)


class OpenAICompatProvider:
    """OpenAI Chat Completions compatible provider (DeepSeek, llama.cpp, vLLM)."""

    id: str

    def __init__(
        self,
        provider_id: str,
        base_url: str,
        api_key: str = "",
        *,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.id = provider_id
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client = client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @asynccontextmanager
    async def _http(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is not None:
            yield self._client
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                yield client

    async def list_models(self) -> list[ModelInfo]:
        try:
            async with self._http() as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                "provider_http_error",
                f"Provider returned HTTP {exc.response.status_code}",
            ) from None
        except httpx.HTTPError as exc:
            raise ProviderError(
                "provider_unreachable", f"Provider unreachable: {type(exc).__name__}"
            ) from None
        except ValueError:
            raise ProviderError("provider_bad_response", "Provider returned invalid JSON") from None

        if not isinstance(payload, dict):
            raise ProviderError(
                "provider_bad_response", "Provider models response is not an object"
            )
        data = payload.get("data")
        if not isinstance(data, list):
            raise ProviderError("provider_bad_response", "Provider models response is missing data")
        return [
            ModelInfo(id=item["id"], provider_id=self.id)
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]

    async def stream_chat(
        self, messages: list[ChatMessage], model: str, **opts: object
    ) -> AsyncIterator[ChatChunk]:
        payload: dict[str, object] = {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        payload.update(opts)
        try:
            async with self._http() as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise ProviderError(
                            "provider_http_error",
                            f"Provider returned HTTP {response.status_code}",
                        )
                    async for line in response.aiter_lines():
                        chunk = self._parse_line(line)
                        if chunk is not None:
                            yield chunk
        except httpx.HTTPError as exc:
            raise ProviderError(
                "provider_unreachable", f"Provider unreachable: {type(exc).__name__}"
            ) from None

    async def complete(
        self, messages: list[ChatMessage], model: str, **opts: object
    ) -> CompletionResult:
        payload: dict[str, object] = {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "stream": False,
        }
        payload.update(opts)
        try:
            async with self._http() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                )
                if response.status_code >= 400:
                    raise ProviderError(
                        "provider_http_error",
                        f"Provider returned HTTP {response.status_code}",
                    )
                body = response.json()
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError(
                "provider_unreachable", f"Provider unreachable: {type(exc).__name__}"
            ) from None
        except ValueError:
            raise ProviderError(
                "provider_bad_response", "Provider returned invalid JSON"
            ) from None

        if not isinstance(body, dict):
            raise ProviderError(
                "provider_bad_response", "Provider completion response is not an object"
            )
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderError(
                "provider_bad_response", "Provider completion response has no choices"
            )
        choice = choices[0]
        message = choice.get("message")
        content = ""
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            content = message["content"]
        finish_reason = choice.get("finish_reason")
        usage_obj = body.get("usage")
        usage: Usage | None = None
        if isinstance(usage_obj, dict):
            prompt_tokens = usage_obj.get("prompt_tokens")
            completion_tokens = usage_obj.get("completion_tokens")
            usage = Usage(
                prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
                completion_tokens=(
                    completion_tokens if isinstance(completion_tokens, int) else None
                ),
            )
        return CompletionResult(
            content=content,
            usage=usage,
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        )

    @staticmethod
    def _parse_line(line: str) -> ChatChunk | None:
        if not line.startswith("data:"):
            return None
        raw = line[len("data:") :].strip()
        if not raw or raw == "[DONE]":
            return None
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(event, dict):
            return None

        delta = ""
        finish_reason: str | None = None
        choices = event.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            choice = choices[0]
            delta_obj = choice.get("delta")
            if isinstance(delta_obj, dict) and isinstance(delta_obj.get("content"), str):
                delta = delta_obj["content"]
            raw_finish = choice.get("finish_reason")
            if isinstance(raw_finish, str):
                finish_reason = raw_finish

        usage_obj = event.get("usage")
        if isinstance(usage_obj, dict):
            prompt_tokens = usage_obj.get("prompt_tokens")
            completion_tokens = usage_obj.get("completion_tokens")
            return ChatChunk(
                delta=delta,
                finish_reason=finish_reason,
                usage=Usage(
                    prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
                    completion_tokens=(
                        completion_tokens if isinstance(completion_tokens, int) else None
                    ),
                ),
            )
        if delta or finish_reason:
            return ChatChunk(delta=delta, finish_reason=finish_reason)
        return None
