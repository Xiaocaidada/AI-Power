"""p2 model catalog

Revision ID: c3d4e5f6a7b8
Revises: 7a1c2e9d4b60
Create Date: 2026-11-21 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "7a1c2e9d4b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_catalog",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("input_price", sa.Float(), nullable=False),
        sa.Column("output_price", sa.Float(), nullable=False),
        sa.Column("tags", sa.String(length=300), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "model_id", name="uq_model_catalog_provider_model"),
    )
    op.create_index(
        op.f("ix_model_catalog_provider_id"), "model_catalog", ["provider_id"], unique=False
    )
    op.create_index(op.f("ix_model_catalog_enabled"), "model_catalog", ["enabled"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_model_catalog_enabled"), table_name="model_catalog")
    op.drop_index(op.f("ix_model_catalog_provider_id"), table_name="model_catalog")
    op.drop_table("model_catalog")
