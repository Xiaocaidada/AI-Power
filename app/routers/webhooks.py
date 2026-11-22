from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import Webhook, WebhookDelivery
from app.schemas import (
    WebhookCreate,
    WebhookCreatedOut,
    WebhookDeliveryOut,
    WebhookOut,
    WebhookUpdate,
)
from app.services.webhooks import (
    encrypt_secret,
    generate_secret,
    parse_events,
    replay_delivery,
    serialize_events,
    validate_webhook_url,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


def _require_owner(context: AuthContext) -> None:
    if context.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only workspace owners can manage webhooks")


async def _get_webhook(session: AsyncSession, webhook_id: UUID, workspace_id: UUID) -> Webhook:
    webhook = (
        await session.execute(
            select(Webhook).where(
                Webhook.id == webhook_id,
                Webhook.workspace_id == workspace_id,
                Webhook.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if webhook is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")
    return webhook


def _out(webhook: Webhook) -> WebhookOut:
    return WebhookOut(
        id=webhook.id,
        url=webhook.url,
        events=parse_events(webhook.events),
        active=webhook.active,
        created_at=webhook.created_at,
    )


async def _validate(url: str) -> None:
    try:
        await validate_webhook_url(url)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "invalid_webhook_url", "message": str(exc)},
        ) from None


@router.get("", response_model=list[WebhookOut])
async def list_webhooks(context: JwtContext, session: SessionDep) -> list[WebhookOut]:
    _require_owner(context)
    hooks = list(
        (
            await session.execute(
                select(Webhook)
                .where(
                    Webhook.workspace_id == context.workspace.id,
                    Webhook.deleted_at.is_(None),
                )
                .order_by(Webhook.created_at.desc())
            )
        ).scalars()
    )
    return [_out(hook) for hook in hooks]


@router.post("", response_model=WebhookCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookCreate, context: JwtContext, session: SessionDep
) -> WebhookCreatedOut:
    _require_owner(context)
    await _validate(payload.url)
    secret = generate_secret()
    hook = Webhook(
        workspace_id=context.workspace.id,
        url=payload.url,
        secret_encrypted=encrypt_secret(secret),
        events=serialize_events(payload.events),
        active=True,
        created_by=context.user.id,
    )
    session.add(hook)
    await session.commit()
    await session.refresh(hook)
    return WebhookCreatedOut(**_out(hook).model_dump(), secret=secret)


@router.patch("/{webhook_id}", response_model=WebhookOut)
async def update_webhook(
    webhook_id: UUID,
    payload: WebhookUpdate,
    context: JwtContext,
    session: SessionDep,
) -> WebhookOut:
    _require_owner(context)
    hook = await _get_webhook(session, webhook_id, context.workspace.id)
    if payload.url is not None and payload.url != hook.url:
        await _validate(payload.url)
        hook.url = payload.url
    if payload.events is not None:
        hook.events = serialize_events(payload.events)
    if payload.active is not None:
        hook.active = payload.active
    await session.commit()
    await session.refresh(hook)
    return _out(hook)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(webhook_id: UUID, context: JwtContext, session: SessionDep) -> Response:
    _require_owner(context)
    hook = await _get_webhook(session, webhook_id, context.workspace.id)
    hook.deleted_at = datetime.now(UTC)
    hook.active = False
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{webhook_id}/deliveries", response_model=list[WebhookDeliveryOut])
async def list_deliveries(
    webhook_id: UUID,
    context: JwtContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[WebhookDelivery]:
    _require_owner(context)
    await _get_webhook(session, webhook_id, context.workspace.id)
    rows = await session.execute(
        select(WebhookDelivery)
        .where(
            WebhookDelivery.webhook_id == webhook_id,
            WebhookDelivery.workspace_id == context.workspace.id,
        )
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
    )
    return list(rows.scalars())


@router.post(
    "/{webhook_id}/deliveries/{delivery_id}/replay",
    response_model=WebhookDeliveryOut,
)
async def replay_webhook_delivery(
    webhook_id: UUID,
    delivery_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> WebhookDelivery:
    _require_owner(context)
    await _get_webhook(session, webhook_id, context.workspace.id)
    delivery = await replay_delivery(session, webhook_id, delivery_id, context.workspace.id)
    if delivery is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook delivery not found")
    return delivery
