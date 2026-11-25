"""p12 provider model thinking configuration

Revision ID: e4f5a6b7c8d9
Revises: d1e2f3a4b5c7
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: str | None = "d1e2f3a4b5c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("provider_models") as batch:
        batch.add_column(
            sa.Column(
                "thinking_config",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("provider_models") as batch:
        batch.drop_column("thinking_config")