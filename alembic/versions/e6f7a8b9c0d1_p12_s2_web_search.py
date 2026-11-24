"""P12-S2: web search provider configs and message sources.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_provider_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("api_key_encrypted", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("api_key_hint", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("max_results", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unknown"),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_search_provider_configs_workspace_id",
        "search_provider_configs",
        ["workspace_id"],
    )
    op.create_index(
        "ix_search_provider_configs_owner_user_id",
        "search_provider_configs",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_search_provider_configs_workspace_deleted",
        "search_provider_configs",
        ["workspace_id", "deleted_at"],
    )
    op.create_table(
        "message_web_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("citation_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("site", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("published_at", sa.String(length=80), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=False, server_default=""),
        sa.Column(
            "provider_config_id",
            sa.Uuid(),
            sa.ForeignKey("search_provider_configs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "message_id", "citation_index", name="uq_message_web_sources_message_index"
        ),
    )
    op.create_index("ix_message_web_sources_message_id", "message_web_sources", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_message_web_sources_message_id", table_name="message_web_sources")
    op.drop_table("message_web_sources")
    op.drop_index(
        "ix_search_provider_configs_workspace_deleted",
        table_name="search_provider_configs",
    )
    op.drop_index("ix_search_provider_configs_owner_user_id", table_name="search_provider_configs")
    op.drop_index("ix_search_provider_configs_workspace_id", table_name="search_provider_configs")
    op.drop_table("search_provider_configs")
