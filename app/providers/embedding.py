from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

import httpx

from app.providers.base import ProviderError


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatEmbeddingProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        *,
        model: str = "bge-m3",
        dimensions: int = 1024,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
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

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.model, "input": texts}
        try:
            async with self._http() as client:
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    json=payload,
                    headers=self._headers(),
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                "embedding_http_error",
                f"Embedding provider returned HTTP {exc.response.status_code}",
            ) from None
        except httpx.HTTPError as exc:
            raise ProviderError(
                "embedding_unreachable",
                f"Embedding provider unreachable: {type(exc).__name__}",
            ) from None
        except ValueError:
            raise ProviderError(
                "embedding_bad_response", "Embedding provider returned invalid JSON"
            ) from None

        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or len(data) != len(texts):
            raise ProviderError("embedding_bad_response", "Embedding response count mismatch")

        ordered = sorted(
            data,
            key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0,
        )
        vectors: list[list[float]] = []
        for item in ordered:
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(embedding, list) or len(embedding) != self.dimensions:
                raise ProviderError("embedding_bad_response", "Embedding dimension mismatch")
            try:
                vectors.append([float(value) for value in embedding])
            except (TypeError, ValueError):
                raise ProviderError(
                    "embedding_bad_response", "Embedding contains non-numeric values"
                ) from None
        return vectors
