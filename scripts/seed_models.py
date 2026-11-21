"""Seed the model catalog from configured providers.

Merges each provider's live model list into `model_catalog`, keeping existing
metadata (prices, tags, context window) and enabling rows that were disabled.

Usage:
    python scripts/seed_models.py
"""

import asyncio

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import ModelCatalog
from app.providers.registry import build_registry


async def seed() -> int:
    await init_db()
    registry = build_registry()
    inserted = 0
    priority = 10

    async with SessionLocal() as session:
        for provider in registry.all():
            try:
                models = await provider.list_models()
            except Exception as exc:
                print(f"skip provider {provider.id}: {exc}")
                continue
            for model in models:
                existing = (
                    await session.execute(
                        select(ModelCatalog).where(
                            ModelCatalog.provider_id == provider.id,
                            ModelCatalog.model_id == model.id,
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.add(
                        ModelCatalog(
                            provider_id=provider.id,
                            model_id=model.id,
                            display_name=model.id.rsplit("/", 1)[-1][:200],
                            priority=priority,
                            enabled=True,
                        )
                    )
                    inserted += 1
                else:
                    existing.enabled = True
                priority += 10
            print(f"provider {provider.id}: {len(models)} models")
        await session.commit()

    return inserted


def main() -> int:
    inserted = asyncio.run(seed())
    print(f"model catalog: {inserted} new rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
