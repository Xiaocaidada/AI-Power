"""p3 usage cost snapshot

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-21 24:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("usage_events") as batch:
        batch.add_column(sa.Column("input_price", sa.Float(), nullable=True))
        batch.add_column(sa.Column("output_price", sa.Float(), nullable=True))
        batch.add_column(sa.Column("cost", sa.Float(), nullable=False, server_default=sa.text("0")))
        batch.add_column(
            sa.Column("unpriced", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("usage_events") as batch:
        batch.drop_column("unpriced")
        batch.drop_column("cost")
        batch.drop_column("output_price")
        batch.drop_column("input_price")
