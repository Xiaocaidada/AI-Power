"""p7 prompt lab and model evaluation

Revision ID: c3d4e5f60718
Revises: b2c3d4e5f607
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f60718"
down_revision: str | None = "b2c3d4e5f607"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("prompt_templates") as batch:
        batch.add_column(
            sa.Column("scope", sa.String(20), nullable=False, server_default="workspace")
        )
        batch.alter_column("workspace_id", existing_type=sa.Uuid(), nullable=True)
    op.create_index("ix_prompt_templates_scope", "prompt_templates", ["scope"])

    with op.batch_alter_table("prompt_versions") as batch:
        batch.add_column(
            sa.Column("user_prompt", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("variable_definitions", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("parameters", sa.JSON(), nullable=False, server_default="{}")
        )

    op.create_table(
        "prompt_experiments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("variables", sa.JSON(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("rating", sa.String(20), nullable=True),
        sa.Column("note", sa.String(1000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["template_id"], ["prompt_templates.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"], ["prompt_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prompt_experiments_workspace_id", "prompt_experiments", ["workspace_id"]
    )
    op.create_index("ix_prompt_experiments_user_id", "prompt_experiments", ["user_id"])
    op.create_index(
        "ix_prompt_experiments_template_id", "prompt_experiments", ["template_id"]
    )
    op.create_index(
        "ix_prompt_experiments_workspace_created",
        "prompt_experiments",
        ["workspace_id", "created_at"],
    )

    op.create_table(
        "prompt_experiment_outputs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("experiment_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.String(50), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ttft_ms", sa.Float(), nullable=True),
        sa.Column("total_ms", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["prompt_experiments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prompt_experiment_outputs_experiment_id",
        "prompt_experiment_outputs",
        ["experiment_id"],
    )

    op.create_table(
        "model_eval_datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_eval_datasets_workspace_id", "model_eval_datasets", ["workspace_id"]
    )

    op.create_table(
        "model_eval_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("scoring_criteria", sa.Text(), nullable=False, server_default=""),
        sa.Column("expected_keywords", sa.JSON(), nullable=False),
        sa.Column("regex", sa.String(500), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["model_eval_datasets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_eval_questions_dataset_id", "model_eval_questions", ["dataset_id"]
    )

    op.create_table(
        "model_eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_running", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_model", sa.String(200), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["model_eval_datasets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_eval_runs_workspace_id", "model_eval_runs", ["workspace_id"])
    op.create_index("ix_model_eval_runs_user_id", "model_eval_runs", ["user_id"])
    op.create_index("ix_model_eval_runs_dataset_id", "model_eval_runs", ["dataset_id"])
    op.create_index(
        "ix_model_eval_runs_workspace_created",
        "model_eval_runs",
        ["workspace_id", "created_at"],
    )

    op.create_table(
        "model_eval_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.String(50), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("question_snapshot", sa.Text(), nullable=False),
        sa.Column("reference_snapshot", sa.Text(), nullable=False, server_default=""),
        sa.Column("answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ttft_ms", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["model_eval_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["question_id"], ["model_eval_questions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "question_id",
            "provider_id",
            "model",
            name="uq_model_eval_items_question_model",
        ),
    )
    op.create_index("ix_model_eval_items_run_id", "model_eval_items", ["run_id"])
    op.create_index(
        "ix_model_eval_items_question_id", "model_eval_items", ["question_id"]
    )

    op.create_table(
        "model_eval_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=False, server_default=""),
        sa.Column("scorer_user_id", sa.Uuid(), nullable=True),
        sa.Column("judge_provider_id", sa.String(50), nullable=True),
        sa.Column("judge_model", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["model_eval_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scorer_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "item_id", "method", "scorer_user_id", name="uq_model_eval_scores_item_method"
        ),
    )
    op.create_index("ix_model_eval_scores_item_id", "model_eval_scores", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_model_eval_scores_item_id", table_name="model_eval_scores")
    op.drop_table("model_eval_scores")
    op.drop_index("ix_model_eval_items_question_id", table_name="model_eval_items")
    op.drop_index("ix_model_eval_items_run_id", table_name="model_eval_items")
    op.drop_table("model_eval_items")
    op.drop_index("ix_model_eval_runs_workspace_created", table_name="model_eval_runs")
    op.drop_index("ix_model_eval_runs_dataset_id", table_name="model_eval_runs")
    op.drop_index("ix_model_eval_runs_user_id", table_name="model_eval_runs")
    op.drop_index("ix_model_eval_runs_workspace_id", table_name="model_eval_runs")
    op.drop_table("model_eval_runs")
    op.drop_index(
        "ix_model_eval_questions_dataset_id", table_name="model_eval_questions"
    )
    op.drop_table("model_eval_questions")
    op.drop_index(
        "ix_model_eval_datasets_workspace_id", table_name="model_eval_datasets"
    )
    op.drop_table("model_eval_datasets")
    op.drop_index(
        "ix_prompt_experiment_outputs_experiment_id",
        table_name="prompt_experiment_outputs",
    )
    op.drop_table("prompt_experiment_outputs")
    op.drop_index(
        "ix_prompt_experiments_workspace_created", table_name="prompt_experiments"
    )
    op.drop_index("ix_prompt_experiments_template_id", table_name="prompt_experiments")
    op.drop_index("ix_prompt_experiments_user_id", table_name="prompt_experiments")
    op.drop_index("ix_prompt_experiments_workspace_id", table_name="prompt_experiments")
    op.drop_table("prompt_experiments")
    with op.batch_alter_table("prompt_versions") as batch:
        batch.drop_column("parameters")
        batch.drop_column("variable_definitions")
        batch.drop_column("user_prompt")
    op.drop_index("ix_prompt_templates_scope", table_name="prompt_templates")
    with op.batch_alter_table("prompt_templates") as batch:
        batch.alter_column("workspace_id", existing_type=sa.Uuid(), nullable=False)
        batch.drop_column("scope")