from typing import Any


class AIPowerError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        request_id: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.request_id = request_id
        self.body = body

    def __str__(self) -> str:
        suffix = f" (request_id={self.request_id})" if self.request_id else ""
        return f"[{self.status_code} {self.code}] {self.message}{suffix}"
