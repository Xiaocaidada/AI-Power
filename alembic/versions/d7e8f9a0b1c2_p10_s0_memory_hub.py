"""p10 s0 memory hub foundation

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: str | None = "c6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_memories") as batch:
        batch.add_column(sa.Column("project_id", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column(
                "scope_type", sa.String(20), nullable=False, server_default="global"
            )
        )
        batch.add_column(
            sa.Column("category", sa.String(30), nullable=False, server_default="fact")
        )
        batch.add_column(
            sa.Column("status", sa.String(20), nullable=False, server_default="active")
        )
        batch.add_column(
            sa.Column(
                "source_type", sa.String(30), nullable=False, server_default="manual"
            )
        )
        batch.add_column(sa.Column("source_id", sa.String(100), nullable=True))
        batch.add_column(
            sa.Column(
                "source_ref", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
            )
        )
        batch.add_column(
            sa.Column("confidence", sa.Float(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column(
                "sensitivity", sa.String(20), nullable=False, server_default="normal"
            )
        )
        batch.add_column(
            sa.Column(
                "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
            )
        )
        batch.add_column(
            sa.Column(
                "pinned", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(
            sa.Column(
                "favorite", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(
            sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
        batch.add_column(
            sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("use_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("content_hash", sa.String(64), nullable=True))
        batch.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column(
                "memory_metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.create_foreign_key(
            "fk_agent_memories_project_id",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
    for index in (
        "ix_agent_memories_project_id",
        "ix_agent_memories_scope_type",
        "ix_agent_memories_category",
        "ix_agent_memories_status",
        "ix_agent_memories_content_hash",
    ):
        op.create_index(index, "agent_memories", [index.split("ix_agent_memories_")[1]])
    op.create_index(
        "ix_agent_memories_workspace_user_status",
        "agent_memories",
        ["workspace_id", "user_id", "status"],
    )
    op.execute(
        "UPDATE agent_memories SET scope_type='global', category=kind, "
        "source_type=source, status='active'"
    )

    op.create_table(
        "memory_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("target_memory_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(30), nullable=False, server_default="chat"),
        sa.Column("source_id", sa.String(100), nullable=True),
        sa.Column(
            "source_ref", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("extracted_by", sa.String(120), nullable=True),
        sa.Column(
            "suggested_action", sa.String(20), nullable=False, server_default="create"
        ),
        sa.Column("category", sa.String(30), nullable=False, server_default="fact"),
        sa.Column("scope_type", sa.String(20), nullable=False, server_default="global"),
        sa.Column("title", sa.String(120), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("sensitivity", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_id"], ["custom_agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["target_memory_id"], ["agent_memories.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_candidates_workspace_id", "memory_candidates", ["workspace_id"]
    )
    op.create_index("ix_memory_candidates_user_id", "memory_candidates", ["user_id"])
    op.create_index(
        "ix_memory_candidates_project_id", "memory_candidates", ["project_id"]
    )
    op.create_index("ix_memory_candidates_agent_id", "memory_candidates", ["agent_id"])
    op.create_index("ix_memory_candidates_status", "memory_candidates", ["status"])
    op.create_index(
        "ix_memory_candidates_user_status",
        "memory_candidates",
        ["user_id", "status", "created_at"],
    )

    op.create_table(
        "memory_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        sa.Column(
            "change_reason", sa.String(300), nullable=False, server_default=""
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id"], ["agent_memories.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "memory_id", "version", name="uq_memory_versions_memory_version"
        ),
    )
    op.create_index("ix_memory_versions_memory_id", "memory_versions", ["memory_id"])

    op.create_table(
        "memory_relations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("from_type", sa.String(20), nullable=False, server_default="memory"),
        sa.Column("from_id", sa.Uuid(), nullable=False),
        sa.Column("to_type", sa.String(20), nullable=False, server_default="memory"),
        sa.Column("to_id", sa.Uuid(), nullable=False),
        sa.Column(
            "relation_type", sa.String(30), nullable=False, server_default="related"
        ),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("basis", sa.String(500), nullable=False, server_default=""),
        sa.Column("source", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "from_type",
            "from_id",
            "to_type",
            "to_id",
            "relation_type",
            name="uq_memory_relations_edge",
        ),
    )
    op.create_index(
        "ix_memory_relations_workspace_id", "memory_relations", ["workspace_id"]
    )
    op.create_index("ix_memory_relations_user_id", "memory_relations", ["user_id"])
    op.create_index("ix_memory_relations_from_id", "memory_relations", ["from_id"])
    op.create_index("ix_memory_relations_to_id", "memory_relations", ["to_id"])
    op.create_index(
        "ix_memory_relations_user_created",
        "memory_relations",
        ["user_id", "created_at"],
    )

    op.create_table(
        "memory_usage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("context_type", sa.String(20), nullable=False, server_default="chat"),
        sa.Column("context_id", sa.String(100), nullable=True),
        sa.Column("provider_id", sa.String(50), nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("relevance", sa.Float(), nullable=True),
        sa.Column("injected_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["memory_id"], ["agent_memories.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_usage_events_workspace_id", "memory_usage_events", ["workspace_id"]
    )
    op.create_index(
        "ix_memory_usage_events_user_id", "memory_usage_events", ["user_id"]
    )
    op.create_index(
        "ix_memory_usage_events_memory_id", "memory_usage_events", ["memory_id"]
    )
    op.create_index(
        "ix_memory_usage_user_created",
        "memory_usage_events",
        ["user_id", "created_at"],
    )

    op.create_table(
        "memory_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "auto_extract", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "auto_save", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "require_confirmation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "allowed_categories",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "allow_project_extract",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "allow_agent_extract",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "allow_cross_model",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "max_inject_items", sa.Integer(), nullable=False, server_default="8"
        ),
        sa.Column(
            "max_inject_chars", sa.Integer(), nullable=False, server_default="4000"
        ),
        sa.Column(
            "blocked_topics",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "user_id", name="uq_memory_settings_workspace_user"
        ),
    )
    op.create_index(
        "ix_memory_settings_workspace_id", "memory_settings", ["workspace_id"]
    )
    op.create_index("ix_memory_settings_user_id", "memory_settings", ["user_id"])


def downgrade() -> None:
    op.drop_table("memory_settings")
    op.drop_table("memory_usage_events")
    op.drop_table("memory_relations")
    op.drop_table("memory_versions")
    op.drop_table("memory_candidates")
    op.drop_index(
        "ix_agent_memories_workspace_user_status", table_name="agent_memories"
    )
    for index in (
        "ix_agent_memories_content_hash",
        "ix_agent_memories_status",
        "ix_agent_memories_category",
        "ix_agent_memories_scope_type",
        "ix_agent_memories_project_id",
    ):
        op.drop_index(index, table_name="agent_memories")
    with op.batch_alter_table("agent_memories") as batch:
        batch.drop_constraint("fk_agent_memories_project_id", type_="foreignkey")
        for column in (
            "memory_metadata",
            "version",
            "content_hash",
            "use_count",
            "valid_until",
            "tags",
            "favorite",
            "pinned",
            "enabled",
            "sensitivity",
            "confidence",
            "source_ref",
            "source_id",
            "source_type",
            "status",
            "category",
            "scope_type",
            "project_id",
        ):
            batch.drop_column(column)