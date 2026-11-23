"""p10 s3 memory injection context

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: str | None = "e8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("memory_enabled", sa.Boolean(), nullable=True))
        batch.add_column(
            sa.Column(
                "excluded_memory_ids",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
    with op.batch_alter_table("messages") as batch:
        batch.add_column(
            sa.Column(
                "memory_refs",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("memory_refs")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("excluded_memory_ids")
        batch.drop_column("memory_enabled")