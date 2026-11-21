async def test_healthz_returns_ok(client):
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_reports_database_and_redis(client):
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "ok"},
    }


async def test_readyz_returns_503_when_redis_is_down(client, fake_redis):
    fake_redis.fail = True

    response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["redis"] == "error"
    assert response.json()["checks"]["database"] == "ok"


async def test_readyz_returns_503_when_database_is_down(client):
    from app.db import get_session
    from app.main import app

    class BrokenSession:
        async def execute(self, *_args, **_kwargs):
            raise RuntimeError("db down")

    async def broken_session():
        yield BrokenSession()

    app.dependency_overrides[get_session] = broken_session
    try:
        response = await client.get("/readyz")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "error"
    assert response.json()["checks"]["redis"] == "ok"
