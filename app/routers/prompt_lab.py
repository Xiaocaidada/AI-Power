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
from app.models import PromptExperiment, PromptExperimentOutput
from app.providers.base import ChatMessage, ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import (
    PromptExperimentCreate,
    PromptExperimentOut,
    PromptExperimentOutputOut,
    PromptExperimentUpdate,
)
from app.services.model_stream import ModelStream, sse
from app.services.prompts import (
    MissingPromptVariables,
    get_accessible_template,
    pick_version,
    render_prompt_both,
)
from app.services.provider_configs import ProviderConfigError, ensure_model_capability
from app.services.quotas import enforce_quota
from app.services.usage_ledger import SOURCE_PROMPT_LAB

router = APIRouter(prefix="/prompt-lab", tags=["prompt-lab"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
ChatContext = Annotated[AuthContext, Depends(require_scope("chat:write"))]
RedisDep = Annotated[RedisLike, Depends(get_redis)]


async def _get_experiment(
    session: AsyncSession, experiment_id: UUID, workspace_id: UUID
) -> tuple[PromptExperiment, list[PromptExperimentOutput]]:
    experiment = await session.get(PromptExperiment, experiment_id)
    if (
        experiment is None
        or experiment.workspace_id != workspace_id
        or experiment.deleted_at is not None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prompt experiment not found")
    outputs = list(
        (
            await session.execute(
                select(PromptExperimentOutput)
                .where(PromptExperimentOutput.experiment_id == experiment.id)
                .order_by(PromptExperimentOutput.created_at, PromptExperimentOutput.id)
            )
        ).scalars()
    )
    return experiment, outputs


def _experiment_out(
    experiment: PromptExperiment, outputs: list[PromptExperimentOutput]
) -> PromptExperimentOut:
    return PromptExperimentOut(
        id=experiment.id,
        template_id=experiment.template_id,
        version_id=experiment.version_id,
        system_prompt=experiment.system_prompt,
        user_prompt=experiment.user_prompt,
        variables=experiment.variables,
        parameters=experiment.parameters,
        rating=experiment.rating,
        note=experiment.note,
        created_at=experiment.created_at,
        outputs=[PromptExperimentOutputOut.model_validate(item) for item in outputs],
    )


@router.post(
    "/experiments",
    response_model=PromptExperimentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_experiment(
    payload: PromptExperimentCreate,
    context: ChatContext,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_scoped_registry)],
) -> PromptExperimentOut:
    template = await get_accessible_template(
        payload.template_id, context.workspace.id, session
    )
    version = await pick_version(session, template.id, payload.version)
    try:
        system_prompt, user_prompt, _variables = render_prompt_both(
            version.system_prompt,
            version.user_prompt,
            payload.variables,
            version.variable_definitions,
        )
    except MissingPromptVariables as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "missing_variables",
                "message": "Missing prompt variables",
                "missing": exc.missing,
            },
        ) from None
    if not system_prompt and not user_prompt:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "empty_prompt", "message": "Prompt is empty"},
        )

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
                {"code": "duplicate_model", "message": "Duplicate model"},
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

    experiment = PromptExperiment(
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        template_id=template.id,
        version_id=version.id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        variables=payload.variables,
        parameters=payload.parameters.model_dump(exclude_none=True),
    )
    session.add(experiment)
    await session.flush()
    outputs = [
        PromptExperimentOutput(
            experiment_id=experiment.id,
            provider_id=item.provider_id,
            model=item.model,
        )
        for item in payload.models
    ]
    session.add_all(outputs)
    await session.commit()
    await session.refresh(experiment)
    for output in outputs:
        await session.refresh(output)
    return _experiment_out(experiment, outputs)


@router.get("/experiments", response_model=list[PromptExperimentOut])
async def list_experiments(
    context: JwtContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    before: UUID | None = None,
) -> list[PromptExperimentOut]:
    conditions = [
        PromptExperiment.workspace_id == context.workspace.id,
        PromptExperiment.deleted_at.is_(None),
    ]
    if before is not None:
        conditions.append(PromptExperiment.id < before)
    experiments = list(
        (
            await session.execute(
                select(PromptExperiment)
                .where(*conditions)
                .order_by(PromptExperiment.id.desc())
                .limit(limit)
            )
        ).scalars()
    )
    result: list[PromptExperimentOut] = []
    for experiment in experiments:
        _, outputs = await _get_experiment(
            session, experiment.id, context.workspace.id
        )
        result.append(_experiment_out(experiment, outputs))
    return result


@router.get("/experiments/{experiment_id}", response_model=PromptExperimentOut)
async def get_experiment(
    experiment_id: UUID, context: JwtContext, session: SessionDep
) -> PromptExperimentOut:
    experiment, outputs = await _get_experiment(
        session, experiment_id, context.workspace.id
    )
    return _experiment_out(experiment, outputs)


@router.patch("/experiments/{experiment_id}", response_model=PromptExperimentOut)
async def update_experiment(
    experiment_id: UUID,
    payload: PromptExperimentUpdate,
    context: JwtContext,
    session: SessionDep,
) -> PromptExperimentOut:
    experiment, outputs = await _get_experiment(
        session, experiment_id, context.workspace.id
    )
    experiment.rating = payload.rating
    experiment.note = payload.note
    await session.commit()
    await session.refresh(experiment)
    return _experiment_out(experiment, outputs)


@router.delete(
    "/experiments/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_experiment(
    experiment_id: UUID, context: JwtContext, session: SessionDep
) -> None:
    experiment, _ = await _get_experiment(
        session, experiment_id, context.workspace.id
    )
    experiment.deleted_at = datetime.now(UTC)
    await session.commit()


@router.post("/experiments/{experiment_id}/outputs/{output_id}/stream")
async def stream_experiment_output(
    experiment_id: UUID,
    output_id: UUID,
    context: ChatContext,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_scoped_registry)],
    redis: RedisDep,
) -> StreamingResponse:
    experiment, outputs = await _get_experiment(
        session, experiment_id, context.workspace.id
    )
    output = next((item for item in outputs if item.id == output_id), None)
    if output is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Output not found")
    if output.status == "streaming":
        raise HTTPException(status.HTTP_409_CONFLICT, "Output is already streaming")
    await enforce_quota(redis, context)
    try:
        provider = registry.get(output.provider_id)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None

    output.status = "streaming"
    output.content = ""
    output.error_code = None
    output.prompt_tokens = None
    output.completion_tokens = None
    output.cost = 0.0
    output.ttft_ms = None
    output.total_ms = None
    await session.commit()

    messages: list[ChatMessage] = []
    if experiment.user_prompt:
        if experiment.system_prompt:
            messages.append(ChatMessage(role="system", content=experiment.system_prompt))
        messages.append(ChatMessage(role="user", content=experiment.user_prompt))
    else:
        messages.append(ChatMessage(role="user", content=experiment.system_prompt))

    async def generator():
        yield sse(
            "meta",
            {
                "output_id": str(output.id),
                "provider_id": output.provider_id,
                "model": output.model,
            },
        )
        stream = ModelStream(
            provider=provider,
            model=output.model,
            messages=messages,
            opts={
                key: value
                for key, value in experiment.parameters.items()
                if value is not None
            },
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            source=SOURCE_PROMPT_LAB,
        )
        try:
            async for event, data in stream.events():
                yield sse(event, data)
        finally:
            async with SessionLocal() as db:
                row = await db.get(PromptExperimentOutput, output.id)
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