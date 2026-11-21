import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import RefreshToken, User


async def _login(client, api, email="refresh@example.com"):
    await api.register(email)
    response = await api.login(email)
    assert response.status_code == 200
    return response.json()


async def test_login_returns_access_and_refresh_tokens(client, api):
    body = await _login(client, api, "tokens@example.com")

    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 30 * 60
    assert body["refresh_expires_in"] == 7 * 24 * 3600
    assert isinstance(body["refresh_token"], str)
    assert len(body["refresh_token"]) >= 40


async def test_refresh_token_is_stored_hashed_and_not_in_plaintext(client, api):
    body = await _login(client, api, "hashed@example.com")

    async with SessionLocal() as session:
        stored = (await session.execute(select(RefreshToken))).scalar_one()

    assert stored.token_hash == hashlib.sha256(body["refresh_token"].encode()).hexdigest()
    assert stored.token_hash != body["refresh_token"]
    assert stored.revoked_at is None
    expires_at = stored.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    assert expires_at > datetime.now(UTC)


async def test_refresh_rotates_token_and_rejects_reuse(client, api):
    first = await _login(client, api, "rotate@example.com")

    rotated_response = await client.post(
        "/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )

    assert rotated_response.status_code == 200
    rotated = rotated_response.json()
    assert rotated["refresh_token"] != first["refresh_token"]
    assert rotated["access_token"] != first["access_token"]
    assert rotated["access_token"]

    reuse = await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reuse.status_code == 401

    async with SessionLocal() as session:
        rows = (
            (await session.execute(select(RefreshToken).order_by(RefreshToken.created_at)))
            .scalars()
            .all()
        )
    assert len(rows) == 2
    assert rows[0].revoked_at is not None
    assert rows[0].replaced_by_id == rows[1].id
    assert rows[1].revoked_at is None


async def test_refresh_rejects_unknown_token(client, api):
    response = await client.post("/auth/refresh", json={"refresh_token": "x" * 64})

    assert response.status_code == 401


async def test_refresh_rejects_expired_token(client, api):
    await api.register("expired-refresh@example.com")
    raw_token = "expired-refresh-" + "x" * 32

    async with SessionLocal() as session:
        user_id = (
            await session.execute(
                select(User.id).where(User.email == "expired-refresh@example.com")
            )
        ).scalar_one()
        session.add(
            RefreshToken(
                user_id=user_id,
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        await session.commit()

    response = await client.post("/auth/refresh", json={"refresh_token": raw_token})

    assert response.status_code == 401


async def test_logout_revokes_refresh_token_and_is_idempotent(client, api):
    body = await _login(client, api, "logout@example.com")

    logout = await client.post("/auth/logout", json={"refresh_token": body["refresh_token"]})

    assert logout.status_code == 204
    reuse = await client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert reuse.status_code == 401
    again = await client.post("/auth/logout", json={"refresh_token": body["refresh_token"]})
    assert again.status_code == 204


async def test_refresh_requires_a_well_formed_token(client):
    response = await client.post("/auth/refresh", json={"refresh_token": ""})

    assert response.status_code == 422
