from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MarketModel, ProviderConfig, ProviderModel
from app.services.provider_configs import (
    add_model,
    create_config,
    list_models,
    update_config,
    update_model,
)


class MarketModelError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _matches(
    model: MarketModel,
    capability: str | None,
    input_type: str | None,
    output_type: str | None,
) -> bool:
    if capability is not None and capability not in model.capabilities:
        return False
    if input_type is not None and input_type not in model.input_types:
        return False
    if output_type is not None and output_type not in model.output_types:
        return False
    return True


async def list_market_models(
    session: AsyncSession,
    *,
    include_disabled: bool = False,
    search: str | None = None,
    category: str | None = None,
    capability: str | None = None,
    provider_id: str | None = None,
    input_type: str | None = None,
    output_type: str | None = None,
    sort: str = "featured",
) -> list[MarketModel]:
    conditions = []
    if not include_disabled:
        conditions.append(MarketModel.enabled.is_(True))
    if category:
        conditions.append(MarketModel.category == category)
    if provider_id:
        conditions.append(MarketModel.provider_id == provider_id)
    if search:
        term = f"%{search.strip()}%"
        conditions.append(
            MarketModel.name.ilike(term)
            | MarketModel.provider_name.ilike(term)
            | MarketModel.model_id.ilike(term)
            | MarketModel.description.ilike(term)
        )
    models = list((await session.execute(select(MarketModel).where(*conditions))).scalars())
    models = [model for model in models if _matches(model, capability, input_type, output_type)]
    if sort == "new":
        models.sort(
            key=lambda model: (
                not model.is_new,
                not model.featured,
                model.sort_order,
                model.name,
            )
        )
    elif sort == "name":
        models.sort(key=lambda model: (model.name.lower(), model.provider_name.lower()))
    else:
        models.sort(key=lambda model: (not model.featured, model.sort_order, model.name))
    return models


async def get_market_model(session: AsyncSession, slug: str) -> MarketModel:
    model = (
        await session.execute(select(MarketModel).where(MarketModel.slug == slug))
    ).scalar_one_or_none()
    if model is None or not model.enabled:
        raise MarketModelError("not_found", "Market model not found")
    return model


async def get_market_model_by_id(session: AsyncSession, model_id: Any) -> MarketModel:
    model = await session.get(MarketModel, model_id)
    if model is None:
        raise MarketModelError("not_found", "Market model not found")
    return model


async def create_market_model(session: AsyncSession, values: dict[str, Any]) -> MarketModel:
    existing = (
        await session.execute(
            select(MarketModel).where(
                (MarketModel.slug == values["slug"])
                | (
                    (MarketModel.provider_id == values["provider_id"])
                    & (MarketModel.model_id == values["model_id"])
                )
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise MarketModelError("duplicate", "Model slug or provider/model already exists")
    model = MarketModel(**values)
    session.add(model)
    await session.flush()
    return model


async def update_market_model(
    session: AsyncSession, model: MarketModel, values: dict[str, Any]
) -> MarketModel:
    for key, value in values.items():
        setattr(model, key, value)
    await session.flush()
    return model


async def delete_market_model(session: AsyncSession, model: MarketModel) -> None:
    await session.delete(model)
    await session.flush()


async def activate_market_model(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    provider_name: str,
    model_id: str,
    display_name: str,
    capabilities: list[str],
    context_window: int,
    max_output: int | None,
    thinking_levels: list[str],
    base_url: str,
    api_key: str,
) -> tuple[ProviderConfig, ProviderModel]:
    """Create or reuse the user's provider config and register one model.

    The credential always comes from the request; nothing is bundled. Reusing a
    config by name keeps repeated activations idempotent while letting the user
    supply a different key/base URL each time.
    """
    name = provider_name.strip()
    config = (
        (
            await session.execute(
                select(ProviderConfig)
                .where(
                    ProviderConfig.workspace_id == workspace_id,
                    ProviderConfig.owner_user_id == user_id,
                    ProviderConfig.deleted_at.is_(None),
                    func.lower(ProviderConfig.name) == name.lower(),
                )
                .order_by(ProviderConfig.created_at)
            )
        )
        .scalars()
        .first()
    )
    if config is None:
        config = await create_config(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            name=name,
            provider_type="openai_compatible",
            base_url=base_url,
            api_key=api_key,
            note="内置模型目录",
        )
    else:
        config = await update_config(session, config, base_url=base_url, api_key=api_key)

    thinking_config = [{"id": level, "label": ""} for level in thinking_levels]
    existing_model = next(
        (item for item in await list_models(session, config.id) if item.model_id == model_id),
        None,
    )
    if existing_model is None:
        model = await add_model(
            session,
            config,
            model_id=model_id,
            display_name=display_name,
            capabilities=capabilities,
            thinking_config=thinking_config,
            context_window=context_window,
            max_output=max_output,
        )
    else:
        model = await update_model(
            session,
            existing_model,
            display_name=display_name,
            capabilities=capabilities,
            thinking_config=thinking_config,
            context_window=context_window,
            max_output=max_output,
            enabled=True,
        )
    return config, model
