"""p6 custom agents and plugins

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-11-23 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: str | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "custom_agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("default_provider_id", sa.String(length=50), nullable=True),
        sa.Column("default_model", sa.String(length=200), nullable=True),
        sa.Column("default_kb_id", sa.Uuid(), nullable=True),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("plugin_ids", sa.JSON(), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["default_kb_id"], ["knowledge_bases.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_custom_agents_workspace_name"),
    )
    op.create_index(
        op.f("ix_custom_agents_workspace_id"), "custom_agents", ["workspace_id"], unique=False
    )
    op.create_index(
        op.f("ix_custom_agents_owner_user_id"), "custom_agents", ["owner_user_id"], unique=False
    )
    op.create_index(
        op.f("ix_custom_agents_category"), "custom_agents", ["category"], unique=False
    )
    op.create_index(
        op.f("ix_custom_agents_visibility"), "custom_agents", ["visibility"], unique=False
    )
    op.create_index(
        "ix_custom_agents_workspace_archived",
        "custom_agents",
        ["workspace_id", "archived_at"],
        unique=False,
    )

    with op.batch_alter_table("conversations", recreate="auto") as batch:
        batch.add_column(sa.Column("custom_agent_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_conversations_custom_agent_id",
            "custom_agents",
            ["custom_agent_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        op.f("ix_conversations_custom_agent_id"),
        "conversations",
        ["custom_agent_id"],
        unique=False,
    )

    op.create_table(
        "plugin_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("docs_url", sa.String(length=500), nullable=False),
        sa.Column("endpoint_url", sa.String(length=1000), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("auth_type", sa.String(length=20), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("sensitive", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_plugin_definitions_slug"), "plugin_definitions", ["slug"], unique=True)
    op.create_index(
        op.f("ix_plugin_definitions_category"), "plugin_definitions", ["category"], unique=False
    )
    op.create_index(
        op.f("ix_plugin_definitions_enabled"), "plugin_definitions", ["enabled"], unique=False
    )

    op.create_table(
        "plugin_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("plugin_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("credential_encrypted", sa.String(length=1000), nullable=False),
        sa.Column("credential_hint", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugin_definitions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "plugin_id", name="uq_plugin_configs_workspace_plugin"),
    )
    op.create_index(
        op.f("ix_plugin_configs_workspace_id"), "plugin_configs", ["workspace_id"], unique=False
    )
    op.create_index(
        op.f("ix_plugin_configs_plugin_id"), "plugin_configs", ["plugin_id"], unique=False
    )

    op.create_table(
        "conversation_plugins",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("plugin_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugin_definitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id", "plugin_id", name="uq_conversation_plugins_conversation_plugin"
        ),
    )
    op.create_index(
        op.f("ix_conversation_plugins_conversation_id"),
        "conversation_plugins",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_plugins_plugin_id"),
        "conversation_plugins",
        ["plugin_id"],
        unique=False,
    )

    op.create_table(
        "plugin_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("plugin_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("request_summary", sa.String(length=500), nullable=False),
        sa.Column("response_summary", sa.String(length=500), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugin_definitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_plugin_calls_workspace_id"), "plugin_calls", ["workspace_id"], unique=False
    )
    op.create_index(
        op.f("ix_plugin_calls_conversation_id"), "plugin_calls", ["conversation_id"], unique=False
    )
    op.create_index(op.f("ix_plugin_calls_plugin_id"), "plugin_calls", ["plugin_id"], unique=False)
    op.create_index(op.f("ix_plugin_calls_status"), "plugin_calls", ["status"], unique=False)
    op.create_index(
        "ix_plugin_calls_workspace_created",
        "plugin_calls",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_plugin_calls_conversation_created",
        "plugin_calls",
        ["conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_plugin_calls_conversation_created", table_name="plugin_calls")
    op.drop_index("ix_plugin_calls_workspace_created", table_name="plugin_calls")
    op.drop_index(op.f("ix_plugin_calls_status"), table_name="plugin_calls")
    op.drop_index(op.f("ix_plugin_calls_plugin_id"), table_name="plugin_calls")
    op.drop_index(op.f("ix_plugin_calls_conversation_id"), table_name="plugin_calls")
    op.drop_index(op.f("ix_plugin_calls_workspace_id"), table_name="plugin_calls")
    op.drop_table("plugin_calls")

    op.drop_index(
        op.f("ix_conversation_plugins_plugin_id"), table_name="conversation_plugins"
    )
    op.drop_index(
        op.f("ix_conversation_plugins_conversation_id"), table_name="conversation_plugins"
    )
    op.drop_table("conversation_plugins")

    op.drop_index(op.f("ix_plugin_configs_plugin_id"), table_name="plugin_configs")
    op.drop_index(op.f("ix_plugin_configs_workspace_id"), table_name="plugin_configs")
    op.drop_table("plugin_configs")

    op.drop_index(op.f("ix_plugin_definitions_enabled"), table_name="plugin_definitions")
    op.drop_index(op.f("ix_plugin_definitions_category"), table_name="plugin_definitions")
    op.drop_index(op.f("ix_plugin_definitions_slug"), table_name="plugin_definitions")
    op.drop_table("plugin_definitions")

    op.drop_index(
        op.f("ix_conversations_custom_agent_id"), table_name="conversations"
    )
    with op.batch_alter_table("conversations", recreate="auto") as batch:
        batch.drop_constraint("fk_conversations_custom_agent_id", type_="foreignkey")
        batch.drop_column("custom_agent_id")

    op.drop_index("ix_custom_agents_workspace_archived", table_name="custom_agents")
    op.drop_index(op.f("ix_custom_agents_visibility"), table_name="custom_agents")
    op.drop_index(op.f("ix_custom_agents_category"), table_name="custom_agents")
    op.drop_index(op.f("ix_custom_agents_owner_user_id"), table_name="custom_agents")
    op.drop_index(op.f("ix_custom_agents_workspace_id"), table_name="custom_agents")
    op.drop_table("custom_agents")