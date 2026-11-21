"""p2 workspaces and workspace scoping

Revision ID: 7a1c2e9d4b60
Revises: 588eba4a32fe
Create Date: 2026-11-21 19:30:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7a1c2e9d4b60"
down_revision: str | None = "588eba4a32fe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPED_TABLES = (
    "knowledge_bases",
    "conversations",
    "documents",
    "chunks",
    "ingestion_jobs",
    "usage_events",
    "api_keys",
)
USER_SCOPED_TABLES = tuple(table for table in SCOPED_TABLES if table != "ingestion_jobs")


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("plan", sa.String(length=20), nullable=False),
        sa.Column("is_personal", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workspaces_is_personal"), "workspaces", ["is_personal"], unique=False)

    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
    )
    op.create_index(
        op.f("ix_workspace_members_workspace_id"),
        "workspace_members",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_members_user_id"), "workspace_members", ["user_id"], unique=False
    )

    for table in SCOPED_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("workspace_id", sa.Uuid(), nullable=True))

    bind = op.get_bind()
    users = bind.execute(sa.text("SELECT id, email FROM users")).all()
    for user_id, email in users:
        workspace_id = uuid.uuid4().hex
        bind.execute(
            sa.text(
                "INSERT INTO workspaces (id, name, plan, is_personal, created_at) "
                "VALUES (:id, :name, 'free', :personal, CURRENT_TIMESTAMP)"
            ),
            {"id": workspace_id, "name": f"{email} 的空间"[:120], "personal": True},
        )
        bind.execute(
            sa.text(
                "INSERT INTO workspace_members (workspace_id, user_id, role, created_at) "
                "VALUES (:workspace_id, :user_id, 'owner', CURRENT_TIMESTAMP)"
            ),
            {"workspace_id": workspace_id, "user_id": user_id},
        )
        for table in USER_SCOPED_TABLES:
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET workspace_id = :workspace_id WHERE user_id = :user_id"
                ),
                {"workspace_id": workspace_id, "user_id": user_id},
            )
    bind.execute(
        sa.text(
            "UPDATE ingestion_jobs SET workspace_id = ("
            "SELECT documents.workspace_id FROM documents "
            "WHERE documents.id = ingestion_jobs.document_id) "
            "WHERE workspace_id IS NULL"
        )
    )

    for table in SCOPED_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column("workspace_id", existing_type=sa.Uuid(), nullable=False)
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"], unique=False)

    inspector = sa.inspect(bind)
    document_indexes = {index["name"] for index in inspector.get_indexes("documents")}
    if "uq_documents_user_kb_hash" in document_indexes:
        op.drop_index("uq_documents_user_kb_hash", table_name="documents")
    op.create_index(
        "uq_documents_workspace_kb_hash",
        "documents",
        ["workspace_id", "kb_id", "content_hash"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    usage_indexes = {index["name"] for index in inspector.get_indexes("usage_events")}
    if "ix_usage_events_user_created" in usage_indexes:
        op.drop_index("ix_usage_events_user_created", table_name="usage_events")
    op.create_index(
        "ix_usage_events_workspace_created",
        "usage_events",
        ["workspace_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_usage_events_workspace_created", table_name="usage_events")
    op.create_index(
        "ix_usage_events_user_created", "usage_events", ["user_id", "created_at"], unique=False
    )

    op.drop_index("uq_documents_workspace_kb_hash", table_name="documents")
    op.create_index(
        "uq_documents_user_kb_hash",
        "documents",
        ["user_id", "kb_id", "content_hash"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    for table in SCOPED_TABLES:
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("workspace_id")

    op.drop_table("workspace_members")
    op.drop_table("workspaces")
