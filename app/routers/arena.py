from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.db import SessionLocal, get_session
from app.deps import AuthContext, get_jwt_context, get_scoped_registry, require_scope
from app.models import ArenaResponse, ArenaRound
from app.providers.base import ChatMessage, ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import (
    ArenaFeedbackIn,
    ArenaResponseOut,
    ArenaRevealOut,
    ArenaRoundCreate,
    ArenaRoundOut,
    ArenaVoteIn,
)
from app.services.model_stream import ModelStream, sse
from app.services.provider_configs import ProviderConfigError, ensure_model_capability
from app.services.quotas import enforce_quota
from app.services.usage_ledger import SOURCE_ARENA

router = APIRouter(prefix="/arena", tags=["arena"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
ChatContext = Annotated[AuthContext, Depends(require_scope("chat:write"))]
RedisDep = Annotated[RedisLike, Depends(get_redis)]

GENERATION_LIMITS = {
    "temperature": (0.0, 2.0),
    "max_tokens": (1, 32768),
    "top_p": (0.0, 1.0),
}


def _normalize_settings(values: dict[str, object] | None) -> dict[str, object]:
    raw = values or {}
    result: dict[str, object] = {}
    for key, (low, high) in GENERATION_LIMITS.items():
        value = raw.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        result[key] = max(low, min(high, int(number) if key == "max_tokens" else number))
    return result


def _label(position: int) -> str:
    return chr(ord("A") + position)


async def _get_round(
    session: AsyncSession, round_id: UUID, workspace_id: UUID
) -> tuple[ArenaRound, list[ArenaResponse]]:
    round_row = await session.get(ArenaRound, round_id)
    if (
        round_row is None
        or round_row.workspace_id != workspace_id
        or round_row.deleted_at is not None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arena round not found")
    responses = list(
        (
            await session.execute(
                select(ArenaResponse)
                .where(ArenaResponse.round_id == round_row.id)
                .order_by(ArenaResponse.position)
            )
        ).scalars()
    )
    return round_row, responses


def _response_out(round_row: ArenaRound, response: ArenaResponse) -> ArenaResponseOut:
    masked = round_row.blind and round_row.revealed_at is None
    return ArenaResponseOut(
        id=response.id,
        position=response.position,
        label=_label(response.position),
        provider_id=None if masked else response.provider_id,
        model=None if masked else response.model,
        status=response.status,
        content=response.content,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        cost=response.cost,
        ttft_ms=response.ttft_ms,
        total_ms=response.total_ms,
        error_code=response.error_code,
        feedback=response.feedback,
        attempt=response.attempt,
    )


def _round_out(round_row: ArenaRound, responses: list[ArenaResponse]) -> ArenaRoundOut:
    return ArenaRoundOut(
        id=round_row.id,
        prompt=round_row.prompt,
        blind=round_row.blind,
        revealed=round_row.revealed_at is not None,
        vote_response_id=round_row.vote_response_id,
        vote_reason=round_row.vote_reason,
        generation_settings=round_row.generation_settings,
        created_at=round_row.created_at,
        responses=[_response_out(round_row, item) for item in responses],
    )


@router.post("/rounds", response_model=ArenaRoundOut, status_code=status.HTTP_201_CREATED)
async def create_round(
    payload: ArenaRoundCreate,
    context: ChatContext,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_scoped_registry)],
) -> ArenaRoundOut:
    seen: set[tuple[str, str]] = set()
    for item in payload.models:
        if item.provider_id == "auto":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "explicit_model_required", "message": "Choose explicit models"},
            )
        key = (item.provider_id, item.model)
        if key in seen:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "duplicate_model", "message": "Duplicate model in arena"},
            )
        seen.add(key)
        try:
            registry.get(item.provider_id)
            await ensure_model_capability(
                session,
                workspace_id=context.workspace.id,
                user_id=context.user.id,
                provider_id=item.provider_id,
                model_id=item.model,
                capability="chat",
            )
        except ProviderError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
        except ProviderConfigError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": exc.code, "message": exc.message},
            ) from None

    round_row = ArenaRound(
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        prompt=payload.prompt,
        generation_settings=_normalize_settings(payload.generation_settings.model_dump()),
        blind=payload.blind,
    )
    session.add(round_row)
    await session.flush()
    responses = [
        ArenaResponse(
            round_id=round_row.id,
            position=index,
            provider_id=item.provider_id,
            model=item.model,
        )
        for index, item in enumerate(payload.models)
    ]
    session.add_all(responses)
    await session.commit()
    await session.refresh(round_row)
    for response in responses:
        await session.refresh(response)
    return _round_out(round_row, responses)


@router.get("/rounds", response_model=list[ArenaRoundOut])
async def list_rounds(
    context: JwtContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    before: UUID | None = None,
) -> list[ArenaRoundOut]:
    conditions = [
        ArenaRound.workspace_id == context.workspace.id,
        ArenaRound.deleted_at.is_(None),
    ]
    if before is not None:
        conditions.append(ArenaRound.id < before)
    rounds = list(
        (
            await session.execute(
                select(ArenaRound)
                .where(*conditions)
                .order_by(ArenaRound.id.desc())
                .limit(limit)
            )
        ).scalars()
    )
    result: list[ArenaRoundOut] = []
    for round_row in rounds:
        _, responses = await _get_round(session, round_row.id, context.workspace.id)
        result.append(_round_out(round_row, responses))
    return result


@router.get("/rounds/{round_id}", response_model=ArenaRoundOut)
async def get_round(
    round_id: UUID, context: JwtContext, session: SessionDep
) -> ArenaRoundOut:
    round_row, responses = await _get_round(session, round_id, context.workspace.id)
    return _round_out(round_row, responses)


@router.delete("/rounds/{round_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_round(
    round_id: UUID, context: JwtContext, session: SessionDep
) -> None:
    round_row, _ = await _get_round(session, round_id, context.workspace.id)
    round_row.deleted_at = datetime.now(UTC)
    await session.commit()


@router.post("/rounds/{round_id}/responses/{response_id}/stream")
async def stream_response(
    round_id: UUID,
    response_id: UUID,
    context: ChatContext,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_scoped_registry)],
    redis: RedisDep,
) -> StreamingResponse:
    round_row, responses = await _get_round(session, round_id, context.workspace.id)
    response = next((item for item in responses if item.id == response_id), None)
    if response is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arena response not found")
    if response.status == "streaming":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "already_streaming", "message": "Response is already streaming"},
        )
    await enforce_quota(redis, context)
    try:
        provider = registry.get(response.provider_id)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None

    response.status = "streaming"
    response.content = ""
    response.error_code = None
    response.feedback = None
    response.prompt_tokens = None
    response.completion_tokens = None
    response.cost = 0.0
    response.ttft_ms = None
    response.total_ms = None
    await session.commit()

    masked = round_row.blind and round_row.revealed_at is None
    meta: dict[str, object] = {
        "response_id": str(response.id),
        "label": _label(response.position),
        "blind": round_row.blind,
        "revealed": round_row.revealed_at is not None,
    }
    if not masked:
        meta["provider_id"] = response.provider_id
        meta["model"] = response.model

    async def generator():
        yield sse("meta", meta)
        stream = ModelStream(
            provider=provider,
            model=response.model,
            messages=[ChatMessage(role="user", content=round_row.prompt)],
            opts=_normalize_settings(round_row.generation_settings),
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            source=SOURCE_ARENA,
        )
        try:
            async for event, data in stream.events():
                yield sse(event, data)
        finally:
            async with SessionLocal() as db:
                row = await db.get(ArenaResponse, response.id)
                if row is not None:
                    row.content = stream.metrics.content
                    row.status = stream.metrics.status
                    row.prompt_tokens = stream.metrics.prompt_tokens
                    row.completion_tokens = stream.metrics.completion_tokens
                    row.cost = stream.metrics.cost
                    row.ttft_ms = stream.metrics.ttft_ms
                    row.total_ms = stream.metrics.total_ms
                    row.error_code = stream.metrics.error_code
                    await db.commit()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/rounds/{round_id}/responses/{response_id}/retry",
    response_model=ArenaResponseOut,
)
async def retry_response(
    round_id: UUID,
    response_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> ArenaResponseOut:
    round_row, responses = await _get_round(session, round_id, context.workspace.id)
    response = next((item for item in responses if item.id == response_id), None)
    if response is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arena response not found")
    if response.status == "streaming":
        raise HTTPException(status.HTTP_409_CONFLICT, "Response is still streaming")
    response.status = "queued"
    response.content = ""
    response.error_code = None
    response.feedback = None
    response.prompt_tokens = None
    response.completion_tokens = None
    response.cost = 0.0
    response.ttft_ms = None
    response.total_ms = None
    response.attempt += 1
    await session.commit()
    await session.refresh(response)
    return _response_out(round_row, response)


@router.put(
    "/rounds/{round_id}/responses/{response_id}/feedback",
    response_model=ArenaResponseOut,
)
async def set_response_feedback(
    round_id: UUID,
    response_id: UUID,
    payload: ArenaFeedbackIn,
    context: JwtContext,
    session: SessionDep,
) -> ArenaResponseOut:
    round_row, responses = await _get_round(session, round_id, context.workspace.id)
    response = next((item for item in responses if item.id == response_id), None)
    if response is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arena response not found")
    response.feedback = payload.feedback
    await session.commit()
    await session.refresh(response)
    return _response_out(round_row, response)


@router.post("/rounds/{round_id}/vote", response_model=ArenaRoundOut)
async def vote_round(
    round_id: UUID, payload: ArenaVoteIn, context: JwtContext, session: SessionDep
) -> ArenaRoundOut:
    round_row, responses = await _get_round(session, round_id, context.workspace.id)
    if not any(item.id == payload.response_id for item in responses):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arena response not found")
    round_row.vote_response_id = payload.response_id
    round_row.vote_reason = payload.reason
    await session.commit()
    await session.refresh(round_row)
    return _round_out(round_row, responses)


@router.post("/rounds/{round_id}/reveal", response_model=ArenaRevealOut)
async def reveal_round(
    round_id: UUID, context: JwtContext, session: SessionDep
) -> ArenaRevealOut:
    round_row, responses = await _get_round(session, round_id, context.workspace.id)
    if round_row.revealed_at is None:
        round_row.revealed_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(round_row)
    return ArenaRevealOut(responses=[_response_out(round_row, item) for item in responses])