"""p9 s4 knowledge evaluation metrics and optimization

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("eval_runs") as batch:
        batch.add_column(
            sa.Column("retrieval_workflow_version_id", sa.Uuid(), nullable=True)
        )
        batch.create_foreign_key(
            "fk_eval_runs_retrieval_workflow_version_id",
            "workflow_versions",
            ["retrieval_workflow_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_eval_runs_retrieval_workflow_version_id",
        "eval_runs",
        ["retrieval_workflow_version_id"],
    )

    with op.batch_alter_table("eval_run_items") as batch:
        for column in (
            "precision_at_5",
            "recall_at_5",
            "ndcg_at_5",
            "precision_at_10",
            "recall_at_10",
            "ndcg_at_10",
        ):
            batch.add_column(
                sa.Column(column, sa.Float(), nullable=False, server_default="0")
            )
        batch.add_column(sa.Column("retrieval_mode", sa.String(20), nullable=True))
        batch.add_column(
            sa.Column(
                "retrieval_trace",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )

    op.create_table(
        "knowledge_optimizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column("eval_run_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_id", sa.Uuid(), nullable=True),
        sa.Column("base_version_id", sa.Uuid(), nullable=True),
        sa.Column("applied_version_id", sa.Uuid(), nullable=True),
        sa.Column("previous_binding_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="proposed"
        ),
        sa.Column("summary", sa.String(2000), nullable=False, server_default=""),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "suggestions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("proposed_definition", sa.JSON(), nullable=True),
        sa.Column("diff", sa.JSON(), nullable=True),
        sa.Column(
            "metrics_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("provider_id", sa.String(50), nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_knowledge_optimizations_workspace_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["kb_id"],
            ["knowledge_bases.id"],
            name="fk_knowledge_optimizations_kb_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["eval_run_id"],
            ["eval_runs.id"],
            name="fk_knowledge_optimizations_eval_run_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name="fk_knowledge_optimizations_workflow_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["base_version_id"],
            ["workflow_versions.id"],
            name="fk_knowledge_optimizations_base_version_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["applied_version_id"],
            ["workflow_versions.id"],
            name="fk_knowledge_optimizations_applied_version_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["previous_binding_version_id"],
            ["workflow_versions.id"],
            name="fk_knowledge_optimizations_previous_binding_version_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_knowledge_optimizations_created_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_optimizations_workspace_id",
        "knowledge_optimizations",
        ["workspace_id"],
    )
    op.create_index(
        "ix_knowledge_optimizations_kb_id",
        "knowledge_optimizations",
        ["kb_id"],
    )
    op.create_index(
        "ix_knowledge_optimizations_eval_run_id",
        "knowledge_optimizations",
        ["eval_run_id"],
    )
    op.create_index(
        "ix_knowledge_optimizations_status",
        "knowledge_optimizations",
        ["status"],
    )
    op.create_index(
        "ix_knowledge_optimizations_kb_created",
        "knowledge_optimizations",
        ["kb_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_optimizations_kb_created",
        table_name="knowledge_optimizations",
    )
    for index in (
        "ix_knowledge_optimizations_status",
        "ix_knowledge_optimizations_eval_run_id",
        "ix_knowledge_optimizations_kb_id",
        "ix_knowledge_optimizations_workspace_id",
    ):
        op.drop_index(index, table_name="knowledge_optimizations")
    op.drop_table("knowledge_optimizations")

    with op.batch_alter_table("eval_run_items") as batch:
        batch.drop_column("retrieval_trace")
        batch.drop_column("retrieval_mode")
        for column in (
            "ndcg_at_10",
            "recall_at_10",
            "precision_at_10",
            "ndcg_at_5",
            "recall_at_5",
            "precision_at_5",
        ):
            batch.drop_column(column)

    op.drop_index(
        "ix_eval_runs_retrieval_workflow_version_id", table_name="eval_runs"
    )
    with op.batch_alter_table("eval_runs") as batch:
        batch.drop_constraint(
            "fk_eval_runs_retrieval_workflow_version_id", type_="foreignkey"
        )
        batch.drop_column("retrieval_workflow_version_id")