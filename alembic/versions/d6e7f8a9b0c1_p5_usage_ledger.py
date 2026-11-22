"""p5 unified usage ledger

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-11-22 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: str | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("usage_events", recreate="auto") as batch:
        batch.alter_column("message_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(
            sa.Column(
                "source", sa.String(length=20), nullable=False, server_default=sa.text("'chat'")
            )
        )
        batch.add_column(sa.Column("api_key_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("workflow_node_run_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("collaboration_step_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_usage_events_api_key_id", "api_keys", ["api_key_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_foreign_key(
            "fk_usage_events_workflow_node_run_id",
            "workflow_node_runs",
            ["workflow_node_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_usage_events_collaboration_step_id",
            "collaboration_steps",
            ["collaboration_step_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_usage_events_source", ["source"], unique=False)
        batch.create_index("ix_usage_events_api_key_id", ["api_key_id"], unique=False)
        batch.create_index(
            "ix_usage_events_workflow_node_run_id", ["workflow_node_run_id"], unique=True
        )
        batch.create_index(
            "ix_usage_events_collaboration_step_id", ["collaboration_step_id"], unique=True
        )
        batch.create_index(
            "ix_usage_events_workspace_source_created",
            ["workspace_id", "source", "created_at"],
            unique=False,
        )
        batch.create_index(
            "ix_usage_events_workspace_api_key_created",
            ["workspace_id", "api_key_id", "created_at"],
            unique=False,
        )
    op.execute("UPDATE usage_events SET source = 'chat' WHERE source IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("usage_events", recreate="auto") as batch:
        batch.drop_index("ix_usage_events_workspace_api_key_created")
        batch.drop_index("ix_usage_events_workspace_source_created")
        batch.drop_index("ix_usage_events_collaboration_step_id")
        batch.drop_index("ix_usage_events_workflow_node_run_id")
        batch.drop_index("ix_usage_events_api_key_id")
        batch.drop_index("ix_usage_events_source")
        batch.drop_constraint("fk_usage_events_collaboration_step_id", type_="foreignkey")
        batch.drop_constraint("fk_usage_events_workflow_node_run_id", type_="foreignkey")
        batch.drop_constraint("fk_usage_events_api_key_id", type_="foreignkey")
        batch.drop_column("collaboration_step_id")
        batch.drop_column("workflow_node_run_id")
        batch.drop_column("api_key_id")
        batch.drop_column("source")
        batch.alter_column("message_id", existing_type=sa.Uuid(), nullable=False)
