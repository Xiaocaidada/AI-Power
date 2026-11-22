"""p5 evaluation platform

Revision ID: b4c5d6e7f8a9
Revises: f2a3b4c5d6e7
Create Date: 2026-11-22 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_eval_datasets_workspace_id"), "eval_datasets", ["workspace_id"], unique=False
    )

    op.create_table(
        "eval_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("relevant_document_ids", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["eval_datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_eval_questions_dataset_id"), "eval_questions", ["dataset_id"], unique=False
    )

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=False),
        sa.Column("progress_done", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["eval_datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_eval_runs_dataset_id"), "eval_runs", ["dataset_id"], unique=False)
    op.create_index(op.f("ix_eval_runs_kb_id"), "eval_runs", ["kb_id"], unique=False)
    op.create_index(op.f("ix_eval_runs_status"), "eval_runs", ["status"], unique=False)
    op.create_index(op.f("ix_eval_runs_workspace_id"), "eval_runs", ["workspace_id"], unique=False)
    op.create_index(
        "ix_eval_runs_workspace_created", "eval_runs", ["workspace_id", "created_at"], unique=False
    )

    op.create_table(
        "eval_run_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("hit_rank", sa.Integer(), nullable=True),
        sa.Column("reciprocal_rank", sa.Float(), nullable=False),
        sa.Column("evidence_hit", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("top_document_ids", sa.JSON(), nullable=False),
        sa.Column("top_chunk_ids", sa.JSON(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("judge_score", sa.Integer(), nullable=True),
        sa.Column("judge_faithful", sa.Boolean(), nullable=True),
        sa.Column("judge_reason", sa.String(length=1000), nullable=True),
        sa.Column("judge_error", sa.String(length=100), nullable=True),
        sa.Column("answer_latency_ms", sa.Float(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["eval_questions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["eval_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "question_id", name="uq_eval_run_items_run_question"),
    )
    op.create_index(op.f("ix_eval_run_items_question_id"), "eval_run_items", ["question_id"])
    op.create_index(op.f("ix_eval_run_items_run_id"), "eval_run_items", ["run_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_eval_run_items_run_id"), table_name="eval_run_items")
    op.drop_index(op.f("ix_eval_run_items_question_id"), table_name="eval_run_items")
    op.drop_table("eval_run_items")
    op.drop_index("ix_eval_runs_workspace_created", table_name="eval_runs")
    op.drop_index(op.f("ix_eval_runs_workspace_id"), table_name="eval_runs")
    op.drop_index(op.f("ix_eval_runs_status"), table_name="eval_runs")
    op.drop_index(op.f("ix_eval_runs_kb_id"), table_name="eval_runs")
    op.drop_index(op.f("ix_eval_runs_dataset_id"), table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index(op.f("ix_eval_questions_dataset_id"), table_name="eval_questions")
    op.drop_table("eval_questions")
    op.drop_index(op.f("ix_eval_datasets_workspace_id"), table_name="eval_datasets")
    op.drop_table("eval_datasets")
