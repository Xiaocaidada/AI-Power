import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
ACCESS_LOGGER = logging.getLogger("app.access")

_STRUCTURED_FIELDS = (
    "event",
    "method",
    "path",
    "status",
    "duration_ms",
    "user_id",
    "provider",
    "model",
    "error_code",
)
_REQUEST_ID_MAX_LENGTH = 64


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_var.get()),
        }
        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        parts = [f"request_id={getattr(record, 'request_id', request_id_var.get())}"]
        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                parts.append(f"{field}={value}")
        return f"{super().format(record)} {' '.join(parts)}"


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


def configure_logging() -> None:
    settings = get_settings()
    level = settings.log_level.upper()
    root = logging.getLogger()
    if getattr(root, "_ai_power_configured", False):
        root.setLevel(level)
        return

    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter("%(levelname)s %(name)s: %(message)s"))
    root.handlers = [handler]
    root.setLevel(level)
    root._ai_power_configured = True  # type: ignore[attr-defined]


def _valid_request_id(value: str) -> bool:
    return (
        0 < len(value) <= _REQUEST_ID_MAX_LENGTH
        and value.isascii()
        and all(character.isalnum() or character in "-_." for character in value)
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("X-Request-ID", "").strip()
        request_id = incoming if _valid_request_id(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            ACCESS_LOGGER.info(
                "request",
                extra={
                    "event": "request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code if response is not None else 500,
                    "duration_ms": duration_ms,
                    "user_id": getattr(request.state, "user_id", None),
                },
            )
            request_id_var.reset(token)
