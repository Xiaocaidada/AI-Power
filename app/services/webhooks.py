import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.models import Webhook, WebhookDelivery

logger = logging.getLogger(__name__)

WEBHOOK_EVENTS = frozenset(
    {
        "message.completed",
        "document.ready",
        "document.failed",
        "workflow.completed",
        "collaboration.completed",
        "budget.exceeded",
    }
)
RETRY_DELAYS_SECONDS = (60, 300, 1800, 7200, 21600)


def serialize_events(events: list[str]) -> str:
    return ",".join(sorted(set(events)))


def parse_events(events: str) -> list[str]:
    return [event for event in events.split(",") if event]


def generate_secret() -> str:
    return f"whsec_{secrets.token_hex(24)}"


def _fernet(settings: Settings | None = None) -> Fernet:
    current = settings or get_settings()
    source = current.webhook_secret_key.strip()
    if not source:
        if current.app_env != "dev":
            raise RuntimeError("WEBHOOK_SECRET_KEY is required outside dev")
        source = current.jwt_secret
    key = base64.urlsafe_b64encode(hashlib.sha256(source.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(secret: str, settings: Settings | None = None) -> str:
    return _fernet(settings).encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_secret(encrypted: str, settings: Settings | None = None) -> str:
    try:
        return _fernet(settings).decrypt(encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        raise ValueError("webhook secret cannot be decrypted") from None


def build_signature(secret: str, timestamp: int, body: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{body}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def validate_url_shape(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("webhook URL must use http or https")
    if not parsed.hostname:
        raise ValueError("webhook URL is missing a hostname")
    if parsed.username or parsed.password:
        raise ValueError("webhook URL must not contain credentials")


def _is_blocked_address(address: str, allow_private: bool) -> bool:
    ip = ipaddress.ip_address(address)
    if ip.is_multicast or ip.is_unspecified:
        return True
    if allow_private:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or getattr(ip, "is_site_local", False)
    )


async def validate_webhook_url(url: str, settings: Settings | None = None) -> None:
    current = settings or get_settings()
    validate_url_shape(url)
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            port,
            0,
            socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ValueError("webhook hostname cannot be resolved") from exc
    if not addresses:
        raise ValueError("webhook hostname cannot be resolved")
    for address in addresses:
        host = str(address[4][0])
        if _is_blocked_address(host, current.webhook_allow_private_hosts):
            raise ValueError("webhook URL resolves to a private or reserved address")


async def enqueue_event(workspace_id: UUID, event: str, payload: dict[str, object]) -> int:
    """Create delivery rows for every active subscription that includes the event."""
    if event not in WEBHOOK_EVENTS:
        logger.warning("unknown webhook event %s", event)
        return 0
    try:
        async with SessionLocal() as session:
            hooks = list(
                (
                    await session.execute(
                        select(Webhook).where(
                            Webhook.workspace_id == workspace_id,
                            Webhook.active.is_(True),
                            Webhook.deleted_at.is_(None),
                        )
                    )
                ).scalars()
            )
            now = datetime.now(UTC)
            created = 0
            for hook in hooks:
                if event not in parse_events(hook.events):
                    continue
                session.add(
                    WebhookDelivery(
                        webhook_id=hook.id,
                        workspace_id=workspace_id,
                        event=event,
                        payload=payload,
                        status="pending",
                        attempts=0,
                        next_attempt_at=now,
                    )
                )
                created += 1
            await session.commit()
            return created
    except Exception:
        logger.exception("failed to enqueue webhook event %s", event)
        return 0


async def deliver_due_deliveries(limit: int = 50) -> int:
    settings = get_settings()
    now = datetime.now(UTC)
    delivered = 0
    async with SessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(WebhookDelivery)
                    .where(
                        WebhookDelivery.status.in_(("pending", "failed")),
                        WebhookDelivery.next_attempt_at <= now,
                    )
                    .order_by(WebhookDelivery.next_attempt_at)
                    .limit(limit)
                )
            ).scalars()
        )
        for delivery in rows:
            hook = await session.get(Webhook, delivery.webhook_id)
            if hook is None or hook.deleted_at is not None or not hook.active:
                delivery.status = "dead"
                delivery.error = "webhook_disabled"
                continue
            try:
                await validate_webhook_url(hook.url, settings)
                secret = decrypt_secret(hook.secret_encrypted, settings)
                body = json.dumps(delivery.payload, ensure_ascii=False, separators=(",", ":"))
                timestamp = int(time.time())
                async with httpx.AsyncClient(
                    timeout=settings.webhook_timeout_seconds,
                    follow_redirects=False,
                ) as client:
                    response = await client.post(
                        hook.url,
                        content=body.encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": "ai-power-webhook/1",
                            "X-AI-Power-Event": delivery.event,
                            "X-AI-Power-Delivery": str(delivery.id),
                            "X-AI-Power-Signature": build_signature(secret, timestamp, body),
                        },
                    )
                delivery.attempts += 1
                delivery.response_status = response.status_code
                if 200 <= response.status_code < 300:
                    delivery.status = "delivered"
                    delivery.error = None
                    delivery.delivered_at = datetime.now(UTC)
                    delivered += 1
                else:
                    _schedule_retry(delivery, f"HTTP {response.status_code}", settings, now)
            except Exception as exc:
                delivery.attempts += 1
                _schedule_retry(delivery, type(exc).__name__, settings, now)
        await session.commit()
    return delivered


def _schedule_retry(
    delivery: WebhookDelivery,
    error: str,
    settings: Settings,
    now: datetime,
) -> None:
    delivery.error = error[:500]
    if delivery.attempts >= settings.webhook_max_attempts:
        delivery.status = "dead"
        return
    delay_index = min(delivery.attempts - 1, len(RETRY_DELAYS_SECONDS) - 1)
    delivery.status = "failed"
    delivery.next_attempt_at = now + timedelta(seconds=RETRY_DELAYS_SECONDS[delay_index])


async def replay_delivery(
    session: AsyncSession, webhook_id: UUID, delivery_id: UUID, workspace_id: UUID
) -> WebhookDelivery | None:
    delivery = (
        await session.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.id == delivery_id,
                WebhookDelivery.webhook_id == webhook_id,
                WebhookDelivery.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if delivery is None:
        return None
    delivery.status = "pending"
    delivery.attempts = 0
    delivery.response_status = None
    delivery.error = None
    delivery.delivered_at = None
    delivery.next_attempt_at = datetime.now(UTC)
    await session.commit()
    return delivery
