import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _request(ip: str) -> Request:
    return Request(
        {
            "type": "http",
            "client": (ip, 1234),
            "headers": [],
            "method": "POST",
            "path": "/auth/login",
        }
    )


async def test_login_is_rate_limited_per_client(client, api, fake_redis):
    await api.register("limited@example.com")

    for _ in range(10):
        response = await api.login("limited@example.com")
        assert response.status_code == 200

    blocked = await api.login("limited@example.com")

    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "login_rate_limited"
    assert int(blocked.headers["Retry-After"]) > 0


async def test_rate_limit_is_keyed_by_client_ip(fake_redis):
    from app.services.rate_limit import enforce_login_rate_limit

    for _ in range(10):
        await enforce_login_rate_limit(_request("10.0.0.1"), fake_redis)

    with pytest.raises(HTTPException) as excinfo:
        await enforce_login_rate_limit(_request("10.0.0.1"), fake_redis)

    assert excinfo.value.status_code == 429
    await enforce_login_rate_limit(_request("10.0.0.2"), fake_redis)


async def test_login_fails_open_when_redis_is_unavailable(client, api, fake_redis):
    fake_redis.fail = True
    await api.register("redis-down@example.com")

    response = await api.login("redis-down@example.com")

    assert response.status_code == 200
