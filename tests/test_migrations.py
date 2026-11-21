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
        "usage_events",
        "message_citations",
        "api_keys",
        "prompt_templates",
        "prompt_versions",
        "audit_logs",
        "alembic_version",
    } <= tables

    refresh_columns = {column["name"] for column in inspector.get_columns("refresh_tokens")}
    assert {"token_hash", "expires_at", "revoked_at", "replaced_by_id"} <= refresh_columns

    job_columns = {column["name"] for column in inspector.get_columns("ingestion_jobs")}
    assert {"started_at", "finished_at", "lease_expires_at"} <= job_columns

    usage_columns = {column["name"] for column in inspector.get_columns("usage_events")}
    assert {
        "user_id",
        "conversation_id",
        "message_id",
        "provider_id",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "input_price",
        "output_price",
        "cost",
        "unpriced",
        "created_at",
    } <= usage_columns

    citation_columns = {column["name"] for column in inspector.get_columns("message_citations")}
    assert {"message_id", "citation_index", "document_id", "chunk_id", "page_no", "snippet"} <= (
        citation_columns
    )

    api_key_columns = {column["name"] for column in inspector.get_columns("api_keys")}
    assert {
        "user_id",
        "name",
        "prefix",
        "key_hash",
        "scopes",
        "last_used_at",
        "revoked_at",
    } <= api_key_columns


def test_usage_backfill_from_existing_messages(tmp_path):
    from uuid import uuid4

    from sqlalchemy import text

    db_path = (tmp_path / "backfill.db").as_posix()
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    command.upgrade(config, "0270a2ddcf33")

    user_id = uuid4().hex
    conversation_id = uuid4().hex
    message_id = uuid4().hex
    now = "2026-11-21 12:00:00.000000"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, role, created_at) "
                "VALUES (:id, 'backfill@example.com', 'x', 'user', :now)"
            ),
            {"id": user_id, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO conversations "
                "(id, user_id, title, provider_id, model, created_at) "
                "VALUES (:id, :user_id, 'Backfill', 'fake', 'fake-model', :now)"
            ),
            {"id": conversation_id, "user_id": user_id, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO messages "
                "(id, conversation_id, user_id, role, content, status, provider_id, model, "
                "prompt_tokens, completion_tokens, created_at) "
                "VALUES (:id, :conversation_id, :user_id, 'assistant', 'Hi', 'completed', "
                "'fake', 'fake-model', 10, 5, :now)"
            ),
            {
                "id": message_id,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "now": now,
            },
        )

    command.upgrade(config, "head")

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT prompt_tokens, completion_tokens FROM usage_events "
                "WHERE message_id = :message_id"
            ),
            {"message_id": message_id},
        ).one()

    assert row == (10, 5)
