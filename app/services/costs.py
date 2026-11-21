from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelCatalog

TOKENS_PER_MILLION = 1_000_000
COST_DECIMALS = 6


async def price_snapshot(
    session: AsyncSession, provider_id: str | None, model: str | None
) -> tuple[float | None, float | None]:
    """Catalog prices for the routed model, if the model is known."""
    if provider_id is None or model is None:
        return None, None
    entry = (
        await session.execute(
            select(ModelCatalog).where(
                ModelCatalog.provider_id == provider_id,
                ModelCatalog.model_id == model,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        return None, None
    return entry.input_price, entry.output_price


def compute_cost(
    prompt_tokens: int | None,
    completion_tokens: int | None,
    input_price: float | None,
    output_price: float | None,
) -> float:
    if input_price is None or output_price is None:
        return 0.0
    prompt = prompt_tokens or 0
    completion = completion_tokens or 0
    cost = (
        prompt / TOKENS_PER_MILLION * input_price + completion / TOKENS_PER_MILLION * output_price
    )
    return round(cost, COST_DECIMALS)
