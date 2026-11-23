"""p10 s2 memory extraction runs

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: str | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_extraction_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False, server_default="message"),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_type", "source_id", name="uq_memory_extraction_source"
        ),
    )
    op.create_index(
        "ix_memory_extraction_runs_workspace_id",
        "memory_extraction_runs",
        ["workspace_id"],
    )
    op.create_index(
        "ix_memory_extraction_runs_user_id", "memory_extraction_runs", ["user_id"]
    )
    op.create_index(
        "ix_memory_extraction_runs_source_id", "memory_extraction_runs", ["source_id"]
    )
    op.create_index(
        "ix_memory_extraction_runs_status", "memory_extraction_runs", ["status"]
    )


def downgrade() -> None:
    op.drop_table("memory_extraction_runs")