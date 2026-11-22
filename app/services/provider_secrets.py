import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings, get_settings


def _fernet(settings: Settings | None = None) -> Fernet:
    current = settings or get_settings()
    source = current.provider_secret_key.strip()
    if not source:
        if current.app_env != "dev":
            raise RuntimeError("PROVIDER_SECRET_KEY is required outside dev")
        source = current.jwt_secret
    key = base64.urlsafe_b64encode(hashlib.sha256(source.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_api_key(api_key: str, settings: Settings | None = None) -> str:
    return _fernet(settings).encrypt(api_key.encode("utf-8")).decode("ascii")


def decrypt_api_key(encrypted: str, settings: Settings | None = None) -> str:
    try:
        return _fernet(settings).decrypt(encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        raise ValueError("provider API key cannot be decrypted") from None


def api_key_hint(api_key: str) -> str:
    if len(api_key) <= 8:
        return "••••"
    return f"••••{api_key[-4:]}"
