"""P11-S8: model and Agent read allowlists for memory.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: str | Sequence[str] | None = "c8d9e0f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory_settings",
        sa.Column("allowed_provider_ids", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "memory_settings",
        sa.Column("allowed_models", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "memory_settings",
        sa.Column("allowed_agent_ids", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("memory_settings", "allowed_agent_ids")
    op.drop_column("memory_settings", "allowed_models")
    op.drop_column("memory_settings", "allowed_provider_ids")