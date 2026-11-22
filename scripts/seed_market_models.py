"""Seed the public marketplace from platform provider model lists.

Run inside the API container:

    docker compose cp scripts/seed_market_models.py api:/tmp/seed_market_models.py
    docker compose exec -T api python /tmp/seed_market_models.py

Idempotent: existing slugs are skipped.
"""

import asyncio
import re

from sqlalchemy import select

from app.db import SessionLocal
from app.models import MarketModel
from app.providers.registry import build_registry

PROVIDER_NAMES = {"local-qwen": "Local Qwen", "deepseek": "DeepSeek"}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:120] or "model"


async def main() -> None:
    registry = build_registry()
    async with SessionLocal() as session:
        added = 0
        for provider in registry.all():
            try:
                models = await provider.list_models()
            except Exception as exc:
                print(f"skip {provider.id}: {type(exc).__name__}")
                continue
            for info in models:
                slug = slugify(f"{provider.id}-{info.id}")[:120]
                existing = (
                    await session.execute(select(MarketModel).where(MarketModel.slug == slug))
                ).scalar_one_or_none()
                if existing is not None:
                    continue
                name = info.id
                if "qwen" in info.id.lower():
                    name = "Qwen2.5 7B Instruct"
                session.add(
                    MarketModel(
                        slug=slug,
                        name=name,
                        provider_id=provider.id,
                        provider_name=PROVIDER_NAMES.get(provider.id, provider.id),
                        model_id=info.id,
                        description="平台已接入的模型。",
                        category="general",
                        capabilities=["chat", "stream"],
                        input_types=["text"],
                        output_types=["text"],
                        context_window=0,
                        featured=provider.id == "local-qwen",
                        is_new=False,
                        sort_order=100,
                    )
                )
                added += 1
        await session.commit()
    print(f"seeded {added} market models")


if __name__ == "__main__":
    asyncio.run(main())
