"""P12-S1: chat modes and model reasoning capabilities.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("default_mode", sa.String(length=20), nullable=False, server_default="chat"),
    )
    op.add_column(
        "messages",
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="chat"),
    )
    op.add_column(
        "messages",
        sa.Column("mode_meta", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "provider_models",
        sa.Column("reasoning_levels", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "model_catalog",
        sa.Column("reasoning_levels", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("model_catalog", "reasoning_levels")
    op.drop_column("provider_models", "reasoning_levels")
    op.drop_column("messages", "mode_meta")
    op.drop_column("messages", "mode")
    op.drop_column("conversations", "default_mode")
