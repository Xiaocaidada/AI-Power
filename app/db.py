from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.models import Base

_settings = get_settings()
_engine_kwargs: dict[str, object] = {}
if _settings.database_url.startswith("sqlite"):
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update(
        pool_size=_settings.db_pool_size,
        max_overflow=_settings.db_max_overflow,
        pool_timeout=_settings.db_pool_timeout_seconds,
    )

engine = create_async_engine(_settings.database_url, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

CHUNK_EMBEDDING_HNSW_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_embedding_hnsw "
    "ON chunk_embeddings USING hnsw (embedding vector_l2_ops)"
)
CHUNK_TEXT_TRGM_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_chunks_text_trgm ON chunks USING gin (text gin_trgm_ops)"
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "postgresql":
            await conn.execute(text(CHUNK_EMBEDDING_HNSW_INDEX_SQL))
            await conn.execute(text(CHUNK_TEXT_TRGM_INDEX_SQL))
