"""p5 async runs and event logs

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-11-23 00:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_runs", recreate="auto") as batch:
        batch.add_column(sa.Column("api_key_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("kb_id", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_foreign_key(
            "fk_workflow_runs_api_key_id", "api_keys", ["api_key_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_foreign_key(
            "fk_workflow_runs_kb_id",
            "knowledge_bases",
            ["kb_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("collaboration_runs", recreate="auto") as batch:
        batch.add_column(sa.Column("api_key_id", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_foreign_key(
            "fk_collaboration_runs_api_key_id",
            "api_keys",
            ["api_key_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "workflow_run_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "seq", name="uq_workflow_run_events_run_seq"),
    )
    op.create_index(
        op.f("ix_workflow_run_events_run_id"), "workflow_run_events", ["run_id"], unique=False
    )
    op.create_index(
        "ix_workflow_run_events_run_seq", "workflow_run_events", ["run_id", "seq"], unique=False
    )

    op.create_table(
        "collaboration_run_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["collaboration_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "seq", name="uq_collaboration_run_events_run_seq"),
    )
    op.create_index(
        op.f("ix_collaboration_run_events_run_id"),
        "collaboration_run_events",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_collaboration_run_events_run_seq",
        "collaboration_run_events",
        ["run_id", "seq"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_collaboration_run_events_run_seq", table_name="collaboration_run_events")
    op.drop_index(op.f("ix_collaboration_run_events_run_id"), table_name="collaboration_run_events")
    op.drop_table("collaboration_run_events")
    op.drop_index("ix_workflow_run_events_run_seq", table_name="workflow_run_events")
    op.drop_index(op.f("ix_workflow_run_events_run_id"), table_name="workflow_run_events")
    op.drop_table("workflow_run_events")

    with op.batch_alter_table("collaboration_runs", recreate="auto") as batch:
        batch.drop_constraint("fk_collaboration_runs_api_key_id", type_="foreignkey")
        batch.drop_column("cancel_requested_at")
        batch.drop_column("api_key_id")

    with op.batch_alter_table("workflow_runs", recreate="auto") as batch:
        batch.drop_constraint("fk_workflow_runs_kb_id", type_="foreignkey")
        batch.drop_constraint("fk_workflow_runs_api_key_id", type_="foreignkey")
        batch.drop_column("cancel_requested_at")
        batch.drop_column("kb_id")
        batch.drop_column("api_key_id")
