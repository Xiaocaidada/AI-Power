from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx

from .errors import AIPowerError
from .sse import SSEEvent, iter_sse

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def _error_from_response(response: httpx.Response) -> AIPowerError:
    body: Any = None
    try:
        body = response.json()
    except ValueError:
        body = response.text[:1000]
    detail = body.get("detail") if isinstance(body, dict) else body
    if isinstance(detail, dict):
        code = str(detail.get("code", "http_error"))
        message = str(detail.get("message") or detail)
    else:
        code = "http_error"
        message = str(detail or response.text[:500])
    return AIPowerError(
        response.status_code,
        code,
        message,
        request_id=response.headers.get("x-request-id"),
        body=body,
    )


def _retry_after(response: httpx.Response) -> float:
    try:
        return max(0.0, float(response.headers.get("retry-after", "1")))
    except ValueError:
        return 1.0


class AIPowerClient:
    """Synchronous client for the AI Power HTTP API."""

    def __init__(
        self,
        base_url: str,
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
        api_key: str | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.api_key = api_key
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> AIPowerClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _headers(self, auth: bool = True) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if auth and self.api_key:
            headers["X-API-Key"] = self.api_key
        elif auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _store_tokens(self, body: dict[str, Any]) -> dict[str, Any]:
        if isinstance(body.get("access_token"), str):
            self.access_token = body["access_token"]
        if isinstance(body.get("refresh_token"), str):
            self.refresh_token = body["refresh_token"]
        return body

    def login(self, email: str, password: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/auth/login",
            auth=False,
            retry=False,
            json={"email": email, "password": password},
        )
        return self._store_tokens(response.json())

    def refresh(self) -> dict[str, Any]:
        if not self.refresh_token:
            raise AIPowerError(401, "no_refresh_token", "No refresh token is available")
        response = self._request(
            "POST",
            "/auth/refresh",
            auth=False,
            retry=False,
            json={"refresh_token": self.refresh_token},
        )
        return self._store_tokens(response.json())

    def _request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        retry: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        refreshed = False
        retries = 0
        while True:
            headers = self._headers(auth)
            headers.update(kwargs.pop("headers", {}) or {})
            response = self._http.request(method, path, headers=headers, **kwargs)
            if response.status_code == 401 and auth and self.refresh_token and not refreshed:
                refreshed = True
                self.refresh()
                continue
            if retry and method == "GET" and response.status_code in RETRY_STATUS and retries < 2:
                time.sleep(_retry_after(response))
                retries += 1
                continue
            if response.is_error:
                raise _error_from_response(response)
            return response

    def models(self) -> list[dict[str, Any]]:
        return self._request("GET", "/models").json()

    def create_conversation(
        self,
        *,
        provider_id: str,
        model: str,
        kb_id: str | None = None,
        agent: bool = False,
        prompt_version_id: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/conversations",
            retry=False,
            json={
                "provider_id": provider_id,
                "model": model,
                "kb_id": kb_id,
                "agent": agent,
                "prompt_version_id": prompt_version_id,
            },
        ).json()

    def chat_stream(self, conversation_id: str, content: str) -> Iterator[SSEEvent]:
        yield from self._stream(
            "POST",
            f"/conversations/{conversation_id}/messages",
            json={"content": content},
        )

    def knowledge_bases(self) -> list[dict[str, Any]]:
        return self._request("GET", "/knowledge-bases").json()

    def create_knowledge_base(self, name: str) -> dict[str, Any]:
        return self._request("POST", "/knowledge-bases", retry=False, json={"name": name}).json()

    def upload_document(
        self,
        kb_id: str,
        filename: str,
        content: bytes,
        *,
        mime: str = "text/plain",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/knowledge-bases/{kb_id}/documents",
            retry=False,
            files={"file": (filename, content, mime)},
        ).json()

    def get_document(self, document_id: str) -> dict[str, Any]:
        return self._request("GET", f"/documents/{document_id}").json()

    def wait_document(
        self, document_id: str, *, timeout: float = 300.0, interval: float = 2.0
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            document = self.get_document(document_id)
            if document.get("status") in {"ready", "failed"}:
                return document
            if time.monotonic() >= deadline:
                raise TimeoutError(f"document {document_id} did not finish in time")
            time.sleep(interval)

    def retrieval_search(
        self,
        kb_id: str,
        query: str,
        *,
        top_k: int | None = None,
        hybrid_enabled: bool | None = None,
        rerank_enabled: bool | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/knowledge-bases/{kb_id}/retrieval/search",
            retry=False,
            json={
                "query": query,
                "top_k": top_k,
                "hybrid_enabled": hybrid_enabled,
                "rerank_enabled": rerank_enabled,
            },
        ).json()

    def workflow_run(
        self,
        workflow_id: str,
        input_text: str,
        *,
        version: int | None = None,
        kb_id: str | None = None,
    ) -> Iterator[SSEEvent]:
        yield from self._stream(
            "POST",
            f"/workflows/{workflow_id}/runs",
            json={"input": input_text, "version": version, "kb_id": kb_id},
        )

    def collaboration_run(
        self,
        input_text: str,
        *,
        provider_id: str,
        model: str,
        kb_id: str | None = None,
    ) -> Iterator[SSEEvent]:
        yield from self._stream(
            "POST",
            "/collaborations/runs",
            json={
                "input": input_text,
                "provider_id": provider_id,
                "model": model,
                "kb_id": kb_id,
            },
        )

    def usage_summary(
        self,
        *,
        from_ts: str | None = None,
        to_ts: str | None = None,
        group_by: str = "day",
    ) -> dict[str, Any]:
        params: dict[str, str] = {"group_by": group_by}
        if from_ts is not None:
            params["from"] = from_ts
        if to_ts is not None:
            params["to"] = to_ts
        return self._request("GET", "/usage/summary", params=params).json()

    def _stream(self, method: str, path: str, **kwargs: Any) -> Iterator[SSEEvent]:
        refreshed = False
        while True:
            headers = self._headers()
            headers.update(kwargs.pop("headers", {}) or {})
            with self._http.stream(method, path, headers=headers, **kwargs) as response:
                if response.status_code == 401 and self.refresh_token and not refreshed:
                    refreshed = True
                    self.refresh()
                    continue
                if response.is_error:
                    response.read()
                    raise _error_from_response(response)
                yield from iter_sse(response.iter_lines())
                return


class AsyncAIPowerClient:
    """Asynchronous client for the AI Power HTTP API."""

    def __init__(
        self,
        base_url: str,
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
        api_key: str | None = None,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.api_key = api_key
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncAIPowerClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    def _headers(self, auth: bool = True) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if auth and self.api_key:
            headers["X-API-Key"] = self.api_key
        elif auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _store_tokens(self, body: dict[str, Any]) -> dict[str, Any]:
        if isinstance(body.get("access_token"), str):
            self.access_token = body["access_token"]
        if isinstance(body.get("refresh_token"), str):
            self.refresh_token = body["refresh_token"]
        return body

    async def login(self, email: str, password: str) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/auth/login",
            auth=False,
            retry=False,
            json={"email": email, "password": password},
        )
        return self._store_tokens(response.json())

    async def refresh(self) -> dict[str, Any]:
        if not self.refresh_token:
            raise AIPowerError(401, "no_refresh_token", "No refresh token is available")
        response = await self._request(
            "POST",
            "/auth/refresh",
            auth=False,
            retry=False,
            json={"refresh_token": self.refresh_token},
        )
        return self._store_tokens(response.json())

    async def _request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        retry: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        refreshed = False
        retries = 0
        while True:
            headers = self._headers(auth)
            headers.update(kwargs.pop("headers", {}) or {})
            response = await self._http.request(method, path, headers=headers, **kwargs)
            if response.status_code == 401 and auth and self.refresh_token and not refreshed:
                refreshed = True
                await self.refresh()
                continue
            if retry and method == "GET" and response.status_code in RETRY_STATUS and retries < 2:
                await asyncio.sleep(_retry_after(response))
                retries += 1
                continue
            if response.is_error:
                raise _error_from_response(response)
            return response

    async def models(self) -> list[dict[str, Any]]:
        return (await self._request("GET", "/models")).json()

    async def create_conversation(
        self,
        *,
        provider_id: str,
        model: str,
        kb_id: str | None = None,
        agent: bool = False,
        prompt_version_id: str | None = None,
    ) -> dict[str, Any]:
        return (
            await self._request(
                "POST",
                "/conversations",
                retry=False,
                json={
                    "provider_id": provider_id,
                    "model": model,
                    "kb_id": kb_id,
                    "agent": agent,
                    "prompt_version_id": prompt_version_id,
                },
            )
        ).json()

    async def chat_stream(self, conversation_id: str, content: str) -> AsyncIterator[SSEEvent]:
        async for event in self._stream(
            "POST",
            f"/conversations/{conversation_id}/messages",
            json={"content": content},
        ):
            yield event

    async def knowledge_bases(self) -> list[dict[str, Any]]:
        return (await self._request("GET", "/knowledge-bases")).json()

    async def create_knowledge_base(self, name: str) -> dict[str, Any]:
        return (
            await self._request("POST", "/knowledge-bases", retry=False, json={"name": name})
        ).json()

    async def upload_document(
        self,
        kb_id: str,
        filename: str,
        content: bytes,
        *,
        mime: str = "text/plain",
    ) -> dict[str, Any]:
        return (
            await self._request(
                "POST",
                f"/knowledge-bases/{kb_id}/documents",
                retry=False,
                files={"file": (filename, content, mime)},
            )
        ).json()

    async def get_document(self, document_id: str) -> dict[str, Any]:
        return (await self._request("GET", f"/documents/{document_id}")).json()

    async def wait_document(
        self, document_id: str, *, timeout: float = 300.0, interval: float = 2.0
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            document = await self.get_document(document_id)
            if document.get("status") in {"ready", "failed"}:
                return document
            if time.monotonic() >= deadline:
                raise TimeoutError(f"document {document_id} did not finish in time")
            await asyncio.sleep(interval)

    async def retrieval_search(
        self,
        kb_id: str,
        query: str,
        *,
        top_k: int | None = None,
        hybrid_enabled: bool | None = None,
        rerank_enabled: bool | None = None,
    ) -> dict[str, Any]:
        return (
            await self._request(
                "POST",
                f"/knowledge-bases/{kb_id}/retrieval/search",
                retry=False,
                json={
                    "query": query,
                    "top_k": top_k,
                    "hybrid_enabled": hybrid_enabled,
                    "rerank_enabled": rerank_enabled,
                },
            )
        ).json()

    async def workflow_run(
        self,
        workflow_id: str,
        input_text: str,
        *,
        version: int | None = None,
        kb_id: str | None = None,
    ) -> AsyncIterator[SSEEvent]:
        async for event in self._stream(
            "POST",
            f"/workflows/{workflow_id}/runs",
            json={"input": input_text, "version": version, "kb_id": kb_id},
        ):
            yield event

    async def collaboration_run(
        self,
        input_text: str,
        *,
        provider_id: str,
        model: str,
        kb_id: str | None = None,
    ) -> AsyncIterator[SSEEvent]:
        async for event in self._stream(
            "POST",
            "/collaborations/runs",
            json={
                "input": input_text,
                "provider_id": provider_id,
                "model": model,
                "kb_id": kb_id,
            },
        ):
            yield event

    async def usage_summary(
        self,
        *,
        from_ts: str | None = None,
        to_ts: str | None = None,
        group_by: str = "day",
    ) -> dict[str, Any]:
        params: dict[str, str] = {"group_by": group_by}
        if from_ts is not None:
            params["from"] = from_ts
        if to_ts is not None:
            params["to"] = to_ts
        return (await self._request("GET", "/usage/summary", params=params)).json()

    async def _stream(self, method: str, path: str, **kwargs: Any) -> AsyncIterator[SSEEvent]:
        refreshed = False
        while True:
            headers = self._headers()
            headers.update(kwargs.pop("headers", {}) or {})
            async with self._http.stream(method, path, headers=headers, **kwargs) as response:
                if response.status_code == 401 and self.refresh_token and not refreshed:
                    refreshed = True
                    await self.refresh()
                    continue
                if response.is_error:
                    await response.aread()
                    raise _error_from_response(response)
                event = "message"
                data: list[str] = []
                async for line in response.aiter_lines():
                    if line == "":
                        if data:
                            yield SSEEvent(event=event, data="\n".join(data))
                        event = "message"
                        data = []
                    elif line.startswith("event:"):
                        event = line[6:].strip() or "message"
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip())
                if data:
                    yield SSEEvent(event=event, data="\n".join(data))
                return
