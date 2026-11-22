from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings, get_settings
from app.providers.base import ProviderError


@dataclass(frozen=True, slots=True)
class RerankResult:
    index: int
    score: float


class Reranker(Protocol):
    async def rerank(
        self, query: str, documents: list[str], top_n: int | None = None
    ) -> list[RerankResult]: ...


class HttpReranker:
    """vLLM / TEI compatible reranker (POST {base_url}/rerank)."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float = 10.0,
        api_key: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @asynccontextmanager
    async def _http(self) -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            yield client

    async def rerank(
        self, query: str, documents: list[str], top_n: int | None = None
    ) -> list[RerankResult]:
        if not documents:
            return []
        payload: dict[str, object] = {
            "model": self.model,
            "query": query,
            "documents": documents,
        }
        if top_n is not None:
            payload["top_n"] = top_n

        try:
            async with self._http() as client:
                response = await client.post(
                    f"{self.base_url}/rerank",
                    json=payload,
                    headers=self._headers(),
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                "rerank_http_error",
                f"Rerank provider returned HTTP {exc.response.status_code}",
            ) from None
        except httpx.HTTPError as exc:
            raise ProviderError(
                "rerank_unreachable",
                f"Rerank provider unreachable: {type(exc).__name__}",
            ) from None
        except ValueError:
            raise ProviderError(
                "rerank_bad_response", "Rerank provider returned invalid JSON"
            ) from None

        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            raise ProviderError("rerank_bad_response", "Rerank response is missing results")

        parsed: list[RerankResult] = []
        seen: set[int] = set()
        for item in results:
            if not isinstance(item, dict):
                raise ProviderError("rerank_bad_response", "Rerank result is malformed")
            index = item.get("index")
            score = item.get("relevance_score", item.get("score"))
            if (
                not isinstance(index, int)
                or index < 0
                or index >= len(documents)
                or index in seen
                or not isinstance(score, (int, float))
            ):
                raise ProviderError("rerank_bad_response", "Rerank result is malformed")
            seen.add(index)
            parsed.append(RerankResult(index=index, score=float(score)))

        parsed.sort(key=lambda result: (-result.score, result.index))
        return parsed


def build_reranker(settings: Settings | None = None) -> HttpReranker | None:
    current = settings or get_settings()
    if not current.rerank_enabled or not current.rerank_base_url.strip():
        return None
    return HttpReranker(
        base_url=current.rerank_base_url,
        model=current.rerank_model,
        timeout=current.rerank_timeout_seconds,
        api_key=current.rerank_api_key,
    )
