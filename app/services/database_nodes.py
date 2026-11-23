"""Admin-managed read-only database targets for workflow nodes."""

import asyncio
import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.models import DatabaseConnection
from app.services.provider_secrets import decrypt_api_key

ALLOWED_DRIVERS = {"postgresql+asyncpg"}
READ_QUERY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
FORBIDDEN_FRAGMENTS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|"
    r"for\s+update|for\s+share|into|pg_sleep|dblink|copy)\b",
    re.IGNORECASE,
)
PARAM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_QUERY_CHARS = 10000


class DatabaseNodeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_dsn(dsn: str) -> URL:
    try:
        url = make_url(dsn.strip())
    except Exception:
        raise DatabaseNodeError("invalid_dsn", "Database DSN is invalid") from None
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+asyncpg")
    if url.drivername not in ALLOWED_DRIVERS:
        raise DatabaseNodeError(
            "invalid_dsn", "Only PostgreSQL (postgresql+asyncpg) is supported"
        )
    if not url.host or not url.database:
        raise DatabaseNodeError("invalid_dsn", "DSN needs a host and database")
    return url


def dsn_hint(dsn: str) -> str:
    try:
        url = normalize_dsn(dsn)
    except DatabaseNodeError:
        return ""
    try:
        rendered = url.render_as_string(hide_password=True)
    except Exception:
        return ""
    return rendered[:200]


def validate_read_query(query: str) -> str:
    stripped = query.strip()
    if not stripped:
        raise DatabaseNodeError("invalid_query", "Query is required")
    if len(stripped) > MAX_QUERY_CHARS:
        raise DatabaseNodeError("invalid_query", "Query is too long")
    if stripped.endswith(";"):
        stripped = stripped[:-1].rstrip()
    if ";" in stripped:
        raise DatabaseNodeError("invalid_query", "Only one statement is allowed")
    if not READ_QUERY.match(stripped):
        raise DatabaseNodeError("invalid_query", "Only SELECT / WITH queries are allowed")
    if FORBIDDEN_FRAGMENTS.search(stripped):
        raise DatabaseNodeError(
            "invalid_query", "Query contains a forbidden read-write fragment"
        )
    return stripped


def validate_params(params: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in params.items():
        if not PARAM_NAME.match(key):
            raise DatabaseNodeError("invalid_params", f"Invalid parameter name: {key}")
        result[key] = value
    return result


def _decrypt(connection: DatabaseConnection) -> URL:
    if not connection.dsn_encrypted:
        raise DatabaseNodeError("database_not_configured", "Database is not configured")
    try:
        dsn = decrypt_api_key(connection.dsn_encrypted)
    except ValueError:
        raise DatabaseNodeError(
            "database_not_configured", "Database credential is invalid"
        ) from None
    return normalize_dsn(dsn)


async def execute_read_query(
    connection: DatabaseConnection,
    query: str,
    params: dict[str, Any] | None = None,
    *,
    max_rows: int | None = None,
    timeout_seconds: float | None = None,
) -> str:
    if not connection.enabled:
        raise DatabaseNodeError("database_disabled", "Database connection is disabled")
    statement = validate_read_query(query)
    bound = validate_params(params or {})
    url = _decrypt(connection)
    limit = max(1, min(max_rows or connection.max_rows, connection.max_rows or 100, 500))
    timeout = max(1.0, float(timeout_seconds or connection.timeout_seconds or 15))

    async def _run() -> str:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(text("SET TRANSACTION READ ONLY"))
                    result = await conn.execute(text(statement), bound)
                    rows = result.mappings().fetchmany(limit)
                    payload = [dict(row) for row in rows]
                finally:
                    await transaction.rollback()
            return json.dumps(payload, ensure_ascii=False, default=str)
        finally:
            await engine.dispose()

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except TimeoutError:
        raise DatabaseNodeError("database_timeout", "Database query timed out") from None
    except DatabaseNodeError:
        raise
    except Exception as exc:
        message = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
        raise DatabaseNodeError("database_error", f"Database query failed: {message}") from None


async def test_connection(connection: DatabaseConnection) -> int:
    url = _decrypt(connection)
    timeout = max(1.0, float(connection.timeout_seconds or 15))

    async def _run() -> int:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                return int(result.scalar_one())
        finally:
            await engine.dispose()

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except TimeoutError:
        raise DatabaseNodeError("database_timeout", "Database connection timed out") from None
    except DatabaseNodeError:
        raise
    except Exception as exc:
        message = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
        raise DatabaseNodeError(
            "database_error", f"Database connection failed: {message}"
        ) from None