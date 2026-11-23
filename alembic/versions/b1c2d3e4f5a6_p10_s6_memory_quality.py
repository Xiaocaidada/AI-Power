"""p10 s6 memory quality, optimization and eval

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_optimizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expected_effect", sa.String(length=500), nullable=False),
        sa.Column("memory_ids", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("before_snapshot", sa.JSON(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_memory_optimizations_workspace_id",
        "memory_optimizations",
        ["workspace_id"],
    )
    op.create_index(
        "ix_memory_optimizations_user_id", "memory_optimizations", ["user_id"]
    )
    op.create_index("ix_memory_optimizations_kind", "memory_optimizations", ["kind"])
    op.create_index("ix_memory_optimizations_status", "memory_optimizations", ["status"])
    op.create_index(
        "ix_memory_optimizations_user_status",
        "memory_optimizations",
        ["user_id", "status", "created_at"],
    )

    op.create_table(
        "memory_eval_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("expected_memory_ids", sa.JSON(), nullable=False),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("custom_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_memory_eval_cases_workspace_id", "memory_eval_cases", ["workspace_id"]
    )
    op.create_index("ix_memory_eval_cases_user_id", "memory_eval_cases", ["user_id"])

    op.create_table(
        "memory_eval_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("cases_count", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_memory_eval_runs_workspace_id", "memory_eval_runs", ["workspace_id"]
    )
    op.create_index("ix_memory_eval_runs_user_id", "memory_eval_runs", ["user_id"])
    op.create_index("ix_memory_eval_runs_status", "memory_eval_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_memory_eval_runs_status", table_name="memory_eval_runs")
    op.drop_index("ix_memory_eval_runs_user_id", table_name="memory_eval_runs")
    op.drop_index("ix_memory_eval_runs_workspace_id", table_name="memory_eval_runs")
    op.drop_table("memory_eval_runs")
    op.drop_index("ix_memory_eval_cases_user_id", table_name="memory_eval_cases")
    op.drop_index("ix_memory_eval_cases_workspace_id", table_name="memory_eval_cases")
    op.drop_table("memory_eval_cases")
    op.drop_index(
        "ix_memory_optimizations_user_status", table_name="memory_optimizations"
    )
    op.drop_index("ix_memory_optimizations_status", table_name="memory_optimizations")
    op.drop_index("ix_memory_optimizations_kind", table_name="memory_optimizations")
    op.drop_index("ix_memory_optimizations_user_id", table_name="memory_optimizations")
    op.drop_index(
        "ix_memory_optimizations_workspace_id", table_name="memory_optimizations"
    )
    op.drop_table("memory_optimizations")