from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def test_alembic_upgrade_head_creates_schema(tmp_path):
    db_path = (tmp_path / "migrated.db").as_posix()
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    tables = set(inspector.get_table_names())

    assert {
        "users",
        "refresh_tokens",
        "knowledge_bases",
        "conversations",
        "messages",
        "documents",
        "chunks",
        "chunk_embeddings",
        "ingestion_jobs",
        "alembic_version",
    } <= tables

    refresh_columns = {column["name"] for column in inspector.get_columns("refresh_tokens")}
    assert {"token_hash", "expires_at", "revoked_at", "replaced_by_id"} <= refresh_columns

    job_columns = {column["name"] for column in inspector.get_columns("ingestion_jobs")}
    assert {"started_at", "finished_at", "lease_expires_at"} <= job_columns
