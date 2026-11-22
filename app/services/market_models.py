from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MarketModel


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
