"""p7 arena feedback and eval scoring snapshots

Revision ID: d4e5f6071829
Revises: c3d4e5f60718
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6071829"
down_revision: str | None = "c3d4e5f60718"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("arena_responses") as batch:
        batch.add_column(sa.Column("feedback", sa.String(20), nullable=True))

    with op.batch_alter_table("model_eval_items") as batch:
        batch.add_column(
            sa.Column("scoring_snapshot", sa.JSON(), nullable=False, server_default="{}")
        )


def downgrade() -> None:
    with op.batch_alter_table("model_eval_items") as batch:
        batch.drop_column("scoring_snapshot")

    with op.batch_alter_table("arena_responses") as batch:
        batch.drop_column("feedback")