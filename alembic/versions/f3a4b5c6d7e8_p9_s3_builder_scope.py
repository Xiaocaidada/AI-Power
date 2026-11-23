"""p9 s3 builder scope

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_builder_sessions") as batch:
        batch.add_column(
            sa.Column(
                "scope", sa.String(30), nullable=False, server_default="agent"
            )
        )
    op.create_index(
        "ix_agent_builder_sessions_scope", "agent_builder_sessions", ["scope"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_builder_sessions_scope", table_name="agent_builder_sessions"
    )
    with op.batch_alter_table("agent_builder_sessions") as batch:
        batch.drop_column("scope")
