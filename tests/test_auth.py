import uuid
from datetime import timedelta

import jwt

from app.config import get_settings


async def test_register_returns_201_and_public_user(client, api):
    response = await api.register("Alice@Example.com")

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["role"] == "user"
    assert uuid.UUID(body["id"])
    assert "password" not in body
    assert "password_hash" not in body
    assert "created_at" in body


async def test_register_duplicate_email_is_case_insensitive(client, api):
    await api.register("dup@example.com")

    response = await api.register("DUP@example.com")

    assert response.status_code == 409


async def test_register_rejects_invalid_email(client, api):
    response = await api.register("not-an-email")

    assert response.status_code == 422


async def test_register_rejects_short_password(client, api):
    response = await api.register("short@example.com", password="short")

    assert response.status_code == 422


async def test_login_returns_bearer_token(client, api):
    await api.register("login@example.com")

    response = await api.login("login@example.com")

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 30 * 60
    assert body["refresh_expires_in"] == 7 * 24 * 3600
    assert body["refresh_token"]
    decoded = jwt.decode(
        body["access_token"],
        get_settings().jwt_secret,
        algorithms=[get_settings().jwt_algorithm],
    )
    assert uuid.UUID(decoded["sub"])


async def test_login_with_wrong_password_is_rejected(client, api):
    await api.register("wrong@example.com")

    response = await api.login("wrong@example.com", password="WrongPass!1")

    assert response.status_code == 401


async def test_login_does_not_reveal_whether_email_exists(client, api):
    await api.register("exists@example.com")

    existing = await api.login("exists@example.com", password="WrongPass!1")
    missing = await api.login("missing@example.com", password="WrongPass!1")

    assert existing.status_code == missing.status_code == 401
    assert existing.json()["detail"] == missing.json()["detail"]


async def test_me_returns_current_user(client, api):
    headers = await api.headers("me@example.com")

    response = await client.get("/auth/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"


async def test_me_without_token_is_rejected(client):
    response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_me_with_malformed_token_is_rejected(client):
    response = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401


async def test_me_with_expired_token_is_rejected(client, api):
    from app.security import create_access_token

    headers = await api.headers("expired@example.com")
    me = await client.get("/auth/me", headers=headers)
    user_id = uuid.UUID(me.json()["id"])
    token = create_access_token(user_id, expires_delta=timedelta(seconds=-1))

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


async def test_me_with_token_for_unknown_user_is_rejected(client):
    from app.security import create_access_token

    token = create_access_token(uuid.uuid4())

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
