import json
import logging

from app.observability import JsonFormatter, request_id_var


async def test_echoes_valid_request_id(client):
    response = await client.get("/healthz", headers={"X-Request-ID": "req-abc-123"})

    assert response.headers["x-request-id"] == "req-abc-123"


async def test_generates_request_id_when_missing(client):
    response = await client.get("/healthz")

    value = response.headers["x-request-id"]
    assert len(value) == 32
    assert all(character in "0123456789abcdef" for character in value)


async def test_replaces_invalid_request_id(client):
    response = await client.get("/healthz", headers={"X-Request-ID": "bad id!"})

    assert response.headers["x-request-id"] != "bad id!"
    assert len(response.headers["x-request-id"]) == 32


async def test_access_log_includes_user_id_and_duration(client, api):
    headers = await api.headers("obs@example.com")

    class Capture(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.records: list[logging.LogRecord] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.records.append(record)

    handler = Capture()
    access_logger = logging.getLogger("app.access")
    previous_level = access_logger.level
    access_logger.setLevel(logging.INFO)
    access_logger.addHandler(handler)
    try:
        response = await client.get("/auth/me", headers=headers)
    finally:
        access_logger.removeHandler(handler)
        access_logger.setLevel(previous_level)

    assert response.status_code == 200
    record = next(
        (item for item in handler.records if getattr(item, "path", "") == "/auth/me"),
        None,
    )
    assert record is not None
    assert record.event == "request"
    assert record.method == "GET"
    assert record.path == "/auth/me"
    assert record.status == 200
    assert record.duration_ms >= 0
    assert record.user_id == response.json()["id"]


def test_json_formatter_includes_request_context():
    token = request_id_var.set("rid-123")
    try:
        record = logging.LogRecord("app.access", logging.INFO, __file__, 1, "request", None, None)
        record.event = "request"
        record.status = 200
        record.duration_ms = 1.2
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)

    assert payload["request_id"] == "rid-123"
    assert payload["level"] == "INFO"
    assert payload["message"] == "request"
    assert payload["status"] == 200
    assert payload["duration_ms"] == 1.2
