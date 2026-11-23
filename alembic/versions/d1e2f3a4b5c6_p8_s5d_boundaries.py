"""p8 s5d boundary completion

Revision ID: d1e2f3a4b5c6
Revises: c93a4b5d6e70
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.vector import EmbeddingVector

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c93a4b5d6e70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "database_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("dsn_encrypted", sa.Text(), nullable=False),
        sa.Column("dsn_hint", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("max_rows", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_database_connections_name"),
    )
    op.create_index(
        "ix_database_connections_enabled", "database_connections", ["enabled"]
    )

    with op.batch_alter_table("workflow_runs") as batch:
        batch.add_column(
            sa.Column(
                "checkpoint",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.add_column(
            sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True)
        )

    with op.batch_alter_table("agent_memories") as batch:
        batch.add_column(sa.Column("embedding", EmbeddingVector(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_memories") as batch:
        batch.drop_column("embedding")
    with op.batch_alter_table("workflow_runs") as batch:
        batch.drop_column("paused_at")
        batch.drop_column("checkpoint")
    op.drop_index(
        "ix_database_connections_enabled", table_name="database_connections"
    )
    op.drop_table("database_connections")