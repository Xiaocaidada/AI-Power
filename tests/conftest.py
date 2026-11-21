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
