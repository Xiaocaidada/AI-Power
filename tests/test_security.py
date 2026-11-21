from datetime import timedelta
from uuid import uuid4

import jwt
import pytest


def test_password_hash_is_salted_and_verifiable():
    from app.security import hash_password, verify_password

    first = hash_password("S3cret!pass")
    second = hash_password("S3cret!pass")

    assert first != second
    assert verify_password("S3cret!pass", first)
    assert not verify_password("wrong", first)


def test_access_token_round_trip():
    from app.security import create_access_token, decode_access_token

    user_id = uuid4()

    token = create_access_token(user_id)

    assert decode_access_token(token) == user_id


def test_expired_access_token_is_rejected():
    from app.security import create_access_token, decode_access_token

    token = create_access_token(uuid4(), expires_delta=timedelta(seconds=-1))

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


def test_malformed_access_token_is_rejected():
    from app.security import decode_access_token

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token("not-a-jwt")


def test_verify_password_rejects_invalid_hash():
    from app.security import verify_password

    assert not verify_password("S3cret!pass", "not-a-valid-hash")


def test_decode_rejects_token_without_access_type():
    from app.config import get_settings
    from app.security import decode_access_token

    settings = get_settings()
    token = jwt.encode(
        {"sub": str(uuid4()), "type": "refresh"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


def test_decode_rejects_token_without_subject():
    from app.config import get_settings
    from app.security import decode_access_token

    settings = get_settings()
    token = jwt.encode({"type": "access"}, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


def test_decode_rejects_non_uuid_subject():
    from app.config import get_settings
    from app.security import decode_access_token

    settings = get_settings()
    token = jwt.encode(
        {"sub": "not-a-uuid", "type": "access"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)
