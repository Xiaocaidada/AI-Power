"""P12-S5: long-running chat tasks and replayable events.

Revision ID: c0d1e2f3a4b5
Revises: a8b9c0d1e2f3
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: str | Sequence[str] | None = "a8b9c0d1e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_tasks",
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
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "kind", sa.String(length=30), nullable=False, server_default="llm_steps"
        ),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("input", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("plan", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("checkpoint", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("result", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pause_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_chat_tasks_workspace_id", "chat_tasks", ["workspace_id"])
    op.create_index("ix_chat_tasks_user_id", "chat_tasks", ["user_id"])
    op.create_index("ix_chat_tasks_conversation_id", "chat_tasks", ["conversation_id"])
    op.create_index("ix_chat_tasks_status", "chat_tasks", ["status"])
    op.create_index(
        "ix_chat_tasks_workspace_status", "chat_tasks", ["workspace_id", "status"]
    )
    op.create_index(
        "ix_chat_tasks_user_created", "chat_tasks", ["user_id", "created_at"]
    )
    op.create_table(
        "chat_task_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("chat_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "seq", name="uq_chat_task_events_task_seq"),
    )
    op.create_index("ix_chat_task_events_task_id", "chat_task_events", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_task_events_task_id", table_name="chat_task_events")
    op.drop_table("chat_task_events")
    op.drop_index("ix_chat_tasks_user_created", table_name="chat_tasks")
    op.drop_index("ix_chat_tasks_workspace_status", table_name="chat_tasks")
    op.drop_index("ix_chat_tasks_status", table_name="chat_tasks")
    op.drop_index("ix_chat_tasks_conversation_id", table_name="chat_tasks")
    op.drop_index("ix_chat_tasks_user_id", table_name="chat_tasks")
    op.drop_index("ix_chat_tasks_workspace_id", table_name="chat_tasks")
    op.drop_table("chat_tasks")