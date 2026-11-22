"""p6 provider hub

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-11-23 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: str | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider_type", sa.String(length=30), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("api_key_encrypted", sa.String(length=1000), nullable=False),
        sa.Column("api_key_hint", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("shared", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_provider_configs_workspace_id"),
        "provider_configs",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_configs_owner_user_id"),
        "provider_configs",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_provider_configs_workspace_deleted",
        "provider_configs",
        ["workspace_id", "deleted_at"],
        unique=False,
    )

    op.create_table(
        "provider_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("config_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["config_id"], ["provider_configs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("config_id", "model_id", name="uq_provider_models_config_model"),
    )
    op.create_index(
        op.f("ix_provider_models_config_id"), "provider_models", ["config_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_provider_models_config_id"), table_name="provider_models")
    op.drop_table("provider_models")
    op.drop_index("ix_provider_configs_workspace_deleted", table_name="provider_configs")
    op.drop_index(
        op.f("ix_provider_configs_owner_user_id"), table_name="provider_configs"
    )
    op.drop_index(op.f("ix_provider_configs_workspace_id"), table_name="provider_configs")
    op.drop_table("provider_configs")