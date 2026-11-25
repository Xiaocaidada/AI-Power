"""p12 provider model context configuration

Revision ID: d1e2f3a4b5c7
Revises: b2c3d4e5f6a7
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e2f3a4b5c7"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("provider_models") as batch:
        batch.add_column(
            sa.Column(
                "context_window",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch.add_column(sa.Column("max_output", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("provider_models") as batch:
        batch.drop_column("max_output")
        batch.drop_column("context_window")
