"""p4 workflows

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-11-21 25:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workflows_workspace_id"), "workflows", ["workspace_id"], unique=False)

    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_version"),
    )
    op.create_index(
        op.f("ix_workflow_versions_workflow_id"),
        "workflow_versions",
        ["workflow_id"],
        unique=False,
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=False),
        sa.Column("total_ms", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["workflow_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workflow_runs_workspace_id"), "workflow_runs", ["workspace_id"], unique=False
    )
    op.create_index(
        op.f("ix_workflow_runs_workflow_id"), "workflow_runs", ["workflow_id"], unique=False
    )
    op.create_index(
        "ix_workflow_runs_workspace_started", "workflow_runs", ["workspace_id", "started_at"]
    )

    op.create_table(
        "workflow_node_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=80), nullable=False),
        sa.Column("node_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("input_summary", sa.String(length=500), nullable=False),
        sa.Column("output_summary", sa.String(length=500), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workflow_node_runs_run_id"), "workflow_node_runs", ["run_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_workflow_node_runs_run_id"), table_name="workflow_node_runs")
    op.drop_table("workflow_node_runs")
    op.drop_index("ix_workflow_runs_workspace_started", table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_workflow_id"), table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_workspace_id"), table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index(op.f("ix_workflow_versions_workflow_id"), table_name="workflow_versions")
    op.drop_table("workflow_versions")
    op.drop_index(op.f("ix_workflows_workspace_id"), table_name="workflows")
    op.drop_table("workflows")
