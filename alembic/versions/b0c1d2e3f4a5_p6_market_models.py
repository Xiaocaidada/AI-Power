"""p6 public model catalog

Revision ID: b0c1d2e3f4a5
Revises: f8a9b0c1d2e3
Create Date: 2026-11-23 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: str | None = "f8a9b0c1d2e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("input_types", sa.JSON(), nullable=False),
        sa.Column("output_types", sa.JSON(), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("max_output", sa.Integer(), nullable=True),
        sa.Column("logo_url", sa.String(length=500), nullable=False),
        sa.Column("docs_url", sa.String(length=500), nullable=False),
        sa.Column("featured", sa.Boolean(), nullable=False),
        sa.Column("is_new", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "model_id", name="uq_market_models_provider_model"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_market_models_slug"), "market_models", ["slug"], unique=True)
    op.create_index(
        op.f("ix_market_models_provider_id"), "market_models", ["provider_id"], unique=False
    )
    op.create_index(
        op.f("ix_market_models_category"), "market_models", ["category"], unique=False
    )
    op.create_index(op.f("ix_market_models_featured"), "market_models", ["featured"], unique=False)
    op.create_index(op.f("ix_market_models_is_new"), "market_models", ["is_new"], unique=False)
    op.create_index(op.f("ix_market_models_enabled"), "market_models", ["enabled"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_market_models_enabled"), table_name="market_models")
    op.drop_index(op.f("ix_market_models_is_new"), table_name="market_models")
    op.drop_index(op.f("ix_market_models_featured"), table_name="market_models")
    op.drop_index(op.f("ix_market_models_category"), table_name="market_models")
    op.drop_index(op.f("ix_market_models_provider_id"), table_name="market_models")
    op.drop_index(op.f("ix_market_models_slug"), table_name="market_models")
    op.drop_table("market_models")