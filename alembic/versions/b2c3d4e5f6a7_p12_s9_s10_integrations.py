"""P12-S9/S10: BYOK integrations, media assets, external calls and skills.

Revision ID: b2c3d4e5f6a7
Revises: c0d1e2f3a4b5
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integration_configs",
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
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column(
            "provider", sa.String(length=40), nullable=False, server_default="openai_compatible"
        ),
        sa.Column("name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("base_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("auth_type", sa.String(length=20), nullable=False, server_default="api_key"),
        sa.Column("credentials_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("credential_hint", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("options", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unknown"),
        sa.Column("last_error", sa.String(length=50), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_integration_configs_workspace_id", "integration_configs", ["workspace_id"]
    )
    op.create_index(
        "ix_integration_configs_owner_user_id", "integration_configs", ["owner_user_id"]
    )
    op.create_index("ix_integration_configs_kind", "integration_configs", ["kind"])
    op.create_index(
        "ix_integration_configs_workspace_kind",
        "integration_configs",
        ["workspace_id", "kind"],
    )
    op.create_index(
        "ix_integration_configs_owner_kind",
        "integration_configs",
        ["owner_user_id", "kind"],
    )

    op.create_table(
        "media_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "integration_id",
            sa.Uuid(),
            sa.ForeignKey("integration_configs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="image"),
        sa.Column("filename", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("mime", sa.String(length=100), nullable=False, server_default="image/png"),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_path", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("asset_metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_media_assets_workspace_id", "media_assets", ["workspace_id"])
    op.create_index("ix_media_assets_user_id", "media_assets", ["user_id"])
    op.create_index("ix_media_assets_kind", "media_assets", ["kind"])
    op.create_index(
        "ix_media_assets_workspace_created", "media_assets", ["workspace_id", "created_at"]
    )

    op.create_table(
        "external_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "integration_id",
            sa.Uuid(),
            sa.ForeignKey("integration_configs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=30), nullable=False, server_default=""),
        sa.Column("provider", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("operation", sa.String(length=60), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("units", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_external_calls_workspace_id", "external_calls", ["workspace_id"])
    op.create_index("ix_external_calls_user_id", "external_calls", ["user_id"])
    op.create_index("ix_external_calls_integration_id", "external_calls", ["integration_id"])
    op.create_index(
        "ix_external_calls_workspace_created", "external_calls", ["workspace_id", "created_at"]
    )

    op.create_table(
        "skills",
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
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_names", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "workspace_id", "owner_user_id", "name", name="uq_skills_owner_name"
        ),
    )
    op.create_index("ix_skills_workspace_id", "skills", ["workspace_id"])
    op.create_index("ix_skills_workspace_enabled", "skills", ["workspace_id", "enabled"])

    op.create_table(
        "skill_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "skill_id",
            sa.Uuid(),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"),
        sa.Column("input", sa.Text(), nullable=False, server_default=""),
        sa.Column("output", sa.Text(), nullable=False, server_default=""),
        sa.Column("provider_id", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("tool_records", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_skill_runs_workspace_id", "skill_runs", ["workspace_id"])
    op.create_index("ix_skill_runs_user_id", "skill_runs", ["user_id"])
    op.create_index("ix_skill_runs_skill_id", "skill_runs", ["skill_id"])
    op.create_index("ix_skill_runs_skill_created", "skill_runs", ["skill_id", "created_at"])


def downgrade() -> None:
    op.drop_table("skill_runs")
    op.drop_table("skills")
    op.drop_table("external_calls")
    op.drop_table("media_assets")
    op.drop_table("integration_configs")