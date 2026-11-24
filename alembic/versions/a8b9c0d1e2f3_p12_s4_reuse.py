"""P12-S4: code snippets, project tasks and conversation shares.

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: str | Sequence[str] | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "code_snippets",
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
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("language", sa.String(length=40), nullable=False, server_default="text"),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_code_snippets_workspace_id", "code_snippets", ["workspace_id"])
    op.create_index("ix_code_snippets_user_id", "code_snippets", ["user_id"])
    op.create_index("ix_code_snippets_project_id", "code_snippets", ["project_id"])
    op.create_index("ix_code_snippets_workspace_user", "code_snippets", ["workspace_id", "user_id"])
    op.create_table(
        "project_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="todo"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column(
            "source_conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_project_tasks_workspace_id", "project_tasks", ["workspace_id"])
    op.create_index("ix_project_tasks_project_id", "project_tasks", ["project_id"])
    op.create_index("ix_project_tasks_user_id", "project_tasks", ["user_id"])
    op.create_index("ix_project_tasks_status", "project_tasks", ["status"])
    op.create_index(
        "ix_project_tasks_workspace_project", "project_tasks", ["workspace_id", "project_id"]
    )
    op.create_table(
        "conversation_shares",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conversation_shares_workspace_id", "conversation_shares", ["workspace_id"])
    op.create_index(
        "ix_conversation_shares_conversation_id",
        "conversation_shares",
        ["conversation_id"],
    )
    op.create_index(
        "ix_conversation_shares_token_hash",
        "conversation_shares",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_shares_token_hash", table_name="conversation_shares")
    op.drop_index("ix_conversation_shares_conversation_id", table_name="conversation_shares")
    op.drop_index("ix_conversation_shares_workspace_id", table_name="conversation_shares")
    op.drop_table("conversation_shares")
    op.drop_index("ix_project_tasks_workspace_project", table_name="project_tasks")
    op.drop_index("ix_project_tasks_status", table_name="project_tasks")
    op.drop_index("ix_project_tasks_user_id", table_name="project_tasks")
    op.drop_index("ix_project_tasks_project_id", table_name="project_tasks")
    op.drop_index("ix_project_tasks_workspace_id", table_name="project_tasks")
    op.drop_table("project_tasks")
    op.drop_index("ix_code_snippets_workspace_user", table_name="code_snippets")
    op.drop_index("ix_code_snippets_project_id", table_name="code_snippets")
    op.drop_index("ix_code_snippets_user_id", table_name="code_snippets")
    op.drop_index("ix_code_snippets_workspace_id", table_name="code_snippets")
    op.drop_table("code_snippets")
