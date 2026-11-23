import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

_TEST_DIR = Path(tempfile.mkdtemp(prefix="ai_power_tests_"))
_UPLOAD_DIR = Path(tempfile.mkdtemp(prefix="ai_power_uploads_"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TEST_DIR / 'test.db').as_posix()}"
os.environ["JWT_SECRET"] = "test-only-secret-0123456789-abcdefghijklmnop"
os.environ["UPLOAD_DIR"] = _UPLOAD_DIR.as_posix()
os.environ["MAX_UPLOAD_BYTES"] = str(20 * 1024 * 1024)
os.environ["MAX_DOCUMENT_PAGES"] = "200"
os.environ["CHUNK_MAX_CHARS"] = "100"
os.environ["CHUNK_OVERLAP_CHARS"] = "20"
os.environ["RERANK_ENABLED"] = "false"
os.environ["EMBEDDING_BATCH_SIZE"] = "2"
os.environ["ACCESS_TOKEN_TTL_MINUTES"] = "30"
os.environ["REFRESH_TOKEN_TTL_DAYS"] = "7"
os.environ["LOGIN_RATE_LIMIT_PER_MINUTE"] = "10"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

DEFAULT_PASSWORD = "S3cret!pass"


@pytest_asyncio.fixture(autouse=True)
async def _reset_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


class Api:
    def __init__(self, http_client: AsyncClient) -> None:
        self.client = http_client
        self.password = DEFAULT_PASSWORD

    async def register(self, email: str, password: str | None = None):
        return await self.client.post(
            "/auth/register",
            json={"email": email, "password": password or self.password},
        )

    async def login(self, email: str, password: str | None = None):
        return await self.client.post(
            "/auth/login",
            json={"email": email, "password": password or self.password},
        )

    async def headers(self, email: str) -> dict[str, str]:
        await self.register(email)
        response = await self.login(email)
        if response.status_code != 200:
            raise AssertionError(f"login failed: {response.status_code} {response.text}")
        return {"Authorization": f"Bearer {response.json()['access_token']}"}


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expirations: dict[str, int] = {}
        self.fail = False

    async def incr(self, key: str) -> int:
        if self.fail:
            raise ConnectionError("redis down")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def incrby(self, key: str, amount: int) -> int:
        if self.fail:
            raise ConnectionError("redis down")
        self.counts[key] = self.counts.get(key, 0) + amount
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        if self.fail:
            raise ConnectionError("redis down")
        self.expirations[key] = seconds
        return True

    async def ttl(self, key: str) -> int:
        if self.fail:
            raise ConnectionError("redis down")
        return self.expirations.get(key, -1)

    async def get(self, key: str) -> str | None:
        if self.fail:
            raise ConnectionError("redis down")
        value = self.counts.get(key)
        return str(value) if value is not None else None

    async def delete(self, key: str) -> int:
        if self.fail:
            raise ConnectionError("redis down")
        return 1 if self.counts.pop(key, None) is not None else 0

    async def ping(self) -> bool:
        if self.fail:
            raise ConnectionError("redis down")
        return True

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def fake_redis():
    from app.clients import get_redis
    from app.main import app as app_instance

    client = FakeRedis()
    app_instance.dependency_overrides[get_redis] = lambda: client
    yield client
    app_instance.dependency_overrides.pop(get_redis, None)


class InlineQueue:
    """Test queue: runs ingestion inline and records enqueued document IDs."""

    def __init__(self) -> None:
        self.calls: list[object] = []
        self.unique_flags: list[bool] = []
        self.eval_calls: list[object] = []
        self.model_eval_calls: list[object] = []
        self.workflow_calls: list[object] = []
        self.collaboration_calls: list[object] = []
        self.fail = False

    async def enqueue_ingestion(self, document_id, *, unique: bool = False) -> None:
        self.calls.append(document_id)
        self.unique_flags.append(unique)
        if self.fail:
            raise ConnectionError("queue down")
        from app.services.ingestion import ingest_document

        await ingest_document(document_id)

    async def enqueue_evaluation(self, run_id) -> None:
        self.eval_calls.append(run_id)
        if self.fail:
            raise ConnectionError("queue down")
        from app.services.evaluation_runner import run_evaluation

        await run_evaluation(run_id)

    async def enqueue_model_eval(self, run_id) -> None:
        self.model_eval_calls.append(run_id)
        if self.fail:
            raise ConnectionError("queue down")
        from app.services.model_eval import execute_model_eval_run

        await execute_model_eval_run(run_id, provider_registry=_provider_registry())

    async def enqueue_workflow_run(self, run_id) -> None:
        self.workflow_calls.append(run_id)
        if self.fail:
            raise ConnectionError("queue down")
        from app.services.run_execution import execute_workflow_run

        await execute_workflow_run(
            run_id, provider_registry=_provider_registry(), redis=_fake_redis()
        )

    async def enqueue_collaboration_run(self, run_id) -> None:
        self.collaboration_calls.append(run_id)
        if self.fail:
            raise ConnectionError("queue down")
        from app.services.run_execution import execute_collaboration_run

        await execute_collaboration_run(
            run_id, provider_registry=_provider_registry(), redis=_fake_redis()
        )


def _provider_registry():
    from app.deps import get_registry
    from app.main import app as app_instance

    override = app_instance.dependency_overrides.get(get_registry)
    return override() if override is not None else None


def _fake_redis():
    from app.clients import get_redis
    from app.main import app as app_instance

    override = app_instance.dependency_overrides.get(get_redis)
    return override() if override is not None else None


@pytest.fixture(autouse=True)
def fake_queue():
    from app.main import app as app_instance
    from app.services.queue import get_queue

    queue = InlineQueue()
    app_instance.dependency_overrides[get_queue] = lambda: queue
    yield queue
    app_instance.dependency_overrides.pop(get_queue, None)


@pytest.fixture
def api(client: AsyncClient) -> Api:
    return Api(client)


@pytest.fixture
def fake_provider():
    from app.providers.base import ChatChunk, CompletionResult, ModelInfo, Usage

    class FakeProvider:
        id = "fake"

        def __init__(self) -> None:
            self.models = [ModelInfo(id="fake-model", provider_id="fake")]
            self.chunks = [
                ChatChunk(delta="Hel"),
                ChatChunk(delta="lo"),
                ChatChunk(usage=Usage(prompt_tokens=1, completion_tokens=2)),
                ChatChunk(finish_reason="stop"),
            ]
            self.error: Exception | None = None
            self.list_models_error: Exception | None = None
            self.calls: list[tuple[list[object], str]] = []
            self.complete_calls: list[tuple[list[object], str]] = []
            self.opts_calls: list[dict[str, object]] = []

        async def list_models(self):
            if self.list_models_error is not None:
                raise self.list_models_error
            return list(self.models)

        async def stream_chat(self, messages, model, **opts):
            self.calls.append((list(messages), model))
            self.opts_calls.append(dict(opts))
            if self.error is not None:
                raise self.error
            for chunk in self.chunks:
                yield chunk

        async def complete(self, messages, model, **opts):
            self.complete_calls.append((list(messages), model))
            self.opts_calls.append(dict(opts))
            if self.error is not None:
                raise self.error
            content = "".join(chunk.delta for chunk in self.chunks)
            usage = next(
                (chunk.usage for chunk in self.chunks if chunk.usage is not None), None
            )
            return CompletionResult(content=content, usage=usage, finish_reason="stop")

    return FakeProvider()


@pytest.fixture
def registry(fake_provider):
    from app.deps import get_registry
    from app.providers.registry import ProviderRegistry

    provider_registry = ProviderRegistry({"fake": fake_provider})
    app.dependency_overrides[get_registry] = lambda: provider_registry
    yield provider_registry
    app.dependency_overrides.pop(get_registry, None)


class KeywordEmbedder:
    """Deterministic 1024-dim embedder: each known keyword maps to one axis."""

    def __init__(self, mapping: dict[str, int] | None = None) -> None:
        self.mapping = dict(mapping or {})
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * 1024
        for keyword, position in self.mapping.items():
            if keyword in text:
                vector[position] = 1.0
        return vector


@pytest.fixture
def keyword_embedder() -> KeywordEmbedder:
    return KeywordEmbedder()


@pytest.fixture
def fake_retrieval(monkeypatch, keyword_embedder):
    from app.services import kb_models

    monkeypatch.setattr(kb_models, "build_embedder", lambda: keyword_embedder)
    return keyword_embedder


@pytest.fixture
def fake_ingestion(monkeypatch):
    from app.services import ingestion
    from app.services.parsing import ParsedDocument, ParsedPage

    class FakeParser:
        def __init__(self) -> None:
            self.pages = [ParsedPage(page_no=1, text="hello world")]
            self.error: Exception | None = None

        def parse(self, path, mime):
            if self.error is not None:
                raise self.error
            return ParsedDocument(pages=self.pages)

    class FakeEmbedder:
        def __init__(self) -> None:
            self.batches: list[list[str]] = []
            self.error: Exception | None = None

        async def embed(self, texts):
            if self.error is not None:
                raise self.error
            self.batches.append(list(texts))
            return [[0.1] * 1024 for _ in texts]

    parser = FakeParser()
    embedder = FakeEmbedder()
    monkeypatch.setattr(ingestion, "build_parser", lambda mime: parser)

    async def fake_kb_embedder(*_args, **_kwargs):
        return embedder

    monkeypatch.setattr(ingestion, "build_kb_embedder", fake_kb_embedder)
    return SimpleNamespace(parser=parser, embedder=embedder)
