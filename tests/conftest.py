import os
import tempfile
from pathlib import Path

_TEST_DIR = Path(tempfile.mkdtemp(prefix="ai_power_tests_"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TEST_DIR / 'test.db').as_posix()}"
os.environ["JWT_SECRET"] = "test-only-secret-0123456789-abcdefghijklmnop"

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


@pytest.fixture
def api(client: AsyncClient) -> Api:
    return Api(client)


@pytest.fixture
def fake_provider():
    from app.providers.base import ChatChunk, ModelInfo, Usage

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

        async def list_models(self):
            if self.list_models_error is not None:
                raise self.list_models_error
            return list(self.models)

        async def stream_chat(self, messages, model, **_opts):
            self.calls.append((list(messages), model))
            if self.error is not None:
                raise self.error
            for chunk in self.chunks:
                yield chunk

    return FakeProvider()


@pytest.fixture
def registry(fake_provider):
    from app.deps import get_registry
    from app.providers.registry import ProviderRegistry

    provider_registry = ProviderRegistry({"fake": fake_provider})
    app.dependency_overrides[get_registry] = lambda: provider_registry
    yield provider_registry
    app.dependency_overrides.pop(get_registry, None)
