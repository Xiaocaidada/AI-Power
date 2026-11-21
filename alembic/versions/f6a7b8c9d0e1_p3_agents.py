"""p3 agents

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-21 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(
            sa.Column("agent", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table("traces") as batch:
        batch.add_column(sa.Column("agents", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("traces") as batch:
        batch.drop_column("agents")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("agent")
