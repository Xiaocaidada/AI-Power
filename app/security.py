import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import get_settings

_hasher = PasswordHasher()

# Verified against when an email does not exist, to keep login timing similar.
DUMMY_PASSWORD_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def generate_refresh_token() -> tuple[str, str]:
    """Return (plaintext token, sha256 hash). Only the hash is stored."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user_id: UUID, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    ttl = (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.access_token_ttl_minutes)
    )
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + ttl,
        "type": "access",
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> UUID:
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("not an access token")
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise jwt.InvalidTokenError("missing subject")
    try:
        return UUID(subject)
    except ValueError as exc:
        raise jwt.InvalidTokenError("invalid subject") from exc
