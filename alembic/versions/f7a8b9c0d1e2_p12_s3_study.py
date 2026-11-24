"""P12-S3: study sessions and quiz attempts.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | Sequence[str] | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "study_sessions",
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
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False, server_default="intermediate"),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="guided"),
        sa.Column("goals", sa.Text(), nullable=False, server_default=""),
        sa.Column("kb_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("mastery", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_study_sessions_workspace_id", "study_sessions", ["workspace_id"])
    op.create_index("ix_study_sessions_user_id", "study_sessions", ["user_id"])
    op.create_index("ix_study_sessions_conversation_id", "study_sessions", ["conversation_id"])
    op.create_index("ix_study_sessions_status", "study_sessions", ["status"])
    op.create_index(
        "ix_study_sessions_user_conversation",
        "study_sessions",
        ["user_id", "conversation_id"],
    )
    op.create_table(
        "study_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("study_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_study_attempts_session_id", "study_attempts", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_study_attempts_session_id", table_name="study_attempts")
    op.drop_table("study_attempts")
    op.drop_index("ix_study_sessions_user_conversation", table_name="study_sessions")
    op.drop_index("ix_study_sessions_status", table_name="study_sessions")
    op.drop_index("ix_study_sessions_conversation_id", table_name="study_sessions")
    op.drop_index("ix_study_sessions_user_id", table_name="study_sessions")
    op.drop_index("ix_study_sessions_workspace_id", table_name="study_sessions")
    op.drop_table("study_sessions")
