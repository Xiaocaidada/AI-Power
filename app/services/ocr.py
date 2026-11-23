"""Optional OCR via an administrator-configured OpenAI-compatible vision model."""

import base64
import logging

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class OcrError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def ocr_ready(settings: Settings | None = None) -> bool:
    current = settings or get_settings()
    return bool(
        current.ocr_enabled
        and current.ocr_base_url.strip()
        and current.ocr_model.strip()
    )


def _chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def ocr_image(data: bytes, mime: str, settings: Settings | None = None) -> str:
    current = settings or get_settings()
    if not ocr_ready(current):
        raise OcrError("ocr_not_configured", "OCR is not configured")
    if len(data) > current.ocr_max_image_bytes:
        raise OcrError("ocr_image_too_large", "OCR image exceeds the configured limit")
    encoded = base64.b64encode(data).decode("ascii")
    payload = {
        "model": current.ocr_model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": current.ocr_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{encoded}"},
                    },
                ],
            }
        ],
    }
    headers = {"Content-Type": "application/json"}
    if current.ocr_api_key.strip():
        headers["Authorization"] = f"Bearer {current.ocr_api_key.strip()}"
    try:
        with httpx.Client(
            timeout=current.ocr_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.post(
                _chat_url(current.ocr_base_url), json=payload, headers=headers
            )
    except httpx.TimeoutException:
        raise OcrError("ocr_timeout", "OCR request timed out") from None
    except httpx.HTTPError as exc:
        raise OcrError(
            "ocr_unreachable", f"OCR endpoint unreachable: {type(exc).__name__}"
        ) from None
    if response.status_code >= 300:
        raise OcrError("ocr_failed", f"OCR endpoint returned HTTP {response.status_code}")
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise OcrError(
            "ocr_bad_response", "OCR endpoint returned an invalid response"
        ) from None
    text = _content_text(content).strip()
    if not text:
        raise OcrError("ocr_empty", "OCR returned no text")
    return text[: current.ocr_max_output_chars]