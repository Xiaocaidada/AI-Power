"""P11-S11: per-memory helpful/unhelpful feedback.

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.String(length=20), nullable=False, server_default="helpful"),
        sa.Column("comment", sa.String(length=500), nullable=False, server_default=""),
        sa.Column(
            "context_type", sa.String(length=20), nullable=False, server_default="manual"
        ),
        sa.Column("context_id", sa.String(length=100), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["memory_id"], ["agent_memories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "memory_id", "user_id", "context_type", "context_id", name="uq_memory_feedback_context"
        ),
    )
    op.create_index("ix_memory_feedback_workspace_id", "memory_feedback", ["workspace_id"])
    op.create_index("ix_memory_feedback_user_id", "memory_feedback", ["user_id"])
    op.create_index("ix_memory_feedback_memory_id", "memory_feedback", ["memory_id"])
    op.create_index(
        "ix_memory_feedback_user_created", "memory_feedback", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_memory_feedback_user_created", table_name="memory_feedback")
    op.drop_index("ix_memory_feedback_memory_id", table_name="memory_feedback")
    op.drop_index("ix_memory_feedback_user_id", table_name="memory_feedback")
    op.drop_index("ix_memory_feedback_workspace_id", table_name="memory_feedback")
    op.drop_table("memory_feedback")