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
        "market_models",
        "home_placements",
        "announcements",
        "announcement_reads",
        "provider_configs",
        "provider_models",
        "prompt_templates",
        "prompt_versions",
        "audit_logs",
        "workflows",
        "workflow_versions",
        "workflow_runs",
        "workflow_node_runs",
        "workflow_run_events",
        "collaboration_runs",
        "collaboration_steps",
        "collaboration_run_events",
        "eval_datasets",
        "eval_questions",
        "eval_runs",
        "eval_run_items",
        "webhooks",
        "webhook_deliveries",
        "alembic_version",
    } <= tables

    refresh_columns = {column["name"] for column in inspector.get_columns("refresh_tokens")}
    assert {"token_hash", "expires_at", "revoked_at", "replaced_by_id"} <= refresh_columns

    job_columns = {column["name"] for column in inspector.get_columns("ingestion_jobs")}
    assert {"started_at", "finished_at", "lease_expires_at"} <= job_columns

    usage_rows = inspector.get_columns("usage_events")
    usage_columns = {column["name"] for column in usage_rows}
    assert {
        "user_id",
        "conversation_id",
        "message_id",
        "source",
        "api_key_id",
        "workflow_node_run_id",
        "collaboration_step_id",
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
    message_column = next(column for column in usage_rows if column["name"] == "message_id")
    assert message_column["nullable"] is True
    usage_indexes = {index["name"] for index in inspector.get_indexes("usage_events")}
    assert {
        "ix_usage_events_workspace_source_created",
        "ix_usage_events_workspace_api_key_created",
        "ix_usage_events_workflow_node_run_id",
        "ix_usage_events_collaboration_step_id",
    } <= usage_indexes

    citation_columns = {column["name"] for column in inspector.get_columns("message_citations")}
    assert {"message_id", "citation_index", "document_id", "chunk_id", "page_no", "snippet"} <= (
        citation_columns
    )

    workflow_run_columns = {column["name"] for column in inspector.get_columns("workflow_runs")}
    assert {"api_key_id", "kb_id", "cancel_requested_at"} <= workflow_run_columns
    collaboration_run_columns = {
        column["name"] for column in inspector.get_columns("collaboration_runs")
    }
    assert {"api_key_id", "cancel_requested_at"} <= collaboration_run_columns
    event_columns = {column["name"] for column in inspector.get_columns("workflow_run_events")}
    assert {"run_id", "seq", "event", "payload", "created_at"} <= event_columns
    collaboration_event_columns = {
        column["name"] for column in inspector.get_columns("collaboration_run_events")
    }
    assert {"run_id", "seq", "event", "payload", "created_at"} <= (collaboration_event_columns)

    market_columns = {column["name"] for column in inspector.get_columns("market_models")}
    assert {
        "slug",
        "name",
        "provider_id",
        "model_id",
        "category",
        "capabilities",
        "context_window",
        "featured",
        "is_new",
        "enabled",
    } <= market_columns

    placement_columns = {column["name"] for column in inspector.get_columns("home_placements")}
    assert {
        "kind",
        "title",
        "subtitle",
        "image_url",
        "link_url",
        "sort_order",
        "enabled",
        "starts_at",
        "ends_at",
    } <= placement_columns
    announcement_columns = {column["name"] for column in inspector.get_columns("announcements")}
    assert {
        "title",
        "summary",
        "body",
        "cover_url",
        "category",
        "pinned",
        "status",
        "published_at",
        "expires_at",
    } <= announcement_columns
    read_columns = {
        column["name"] for column in inspector.get_columns("announcement_reads")
    }
    assert {"announcement_id", "user_id", "read_at"} <= read_columns

    provider_config_columns = {
        column["name"] for column in inspector.get_columns("provider_configs")
    }
    assert {
        "workspace_id",
        "owner_user_id",
        "name",
        "provider_type",
        "base_url",
        "api_key_encrypted",
        "api_key_hint",
        "shared",
        "status",
    } <= provider_config_columns
    provider_model_columns = {column["name"] for column in inspector.get_columns("provider_models")}
    assert {"config_id", "model_id", "capabilities", "source", "enabled"} <= (
        provider_model_columns
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
                "SELECT prompt_tokens, completion_tokens, source FROM usage_events "
                "WHERE message_id = :message_id"
            ),
            {"message_id": message_id},
        ).one()

    assert row == (10, 5, "chat")
