"""p2 traces

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-21 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "traces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("provider_id", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("retrieval_ms", sa.Float(), nullable=True),
        sa.Column("ttft_ms", sa.Float(), nullable=True),
        sa.Column("total_ms", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_traces_request_id"), "traces", ["request_id"], unique=False)
    op.create_index(op.f("ix_traces_workspace_id"), "traces", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_traces_user_id"), "traces", ["user_id"], unique=False)
    op.create_index(op.f("ix_traces_message_id"), "traces", ["message_id"], unique=True)
    op.create_index(
        "ix_traces_workspace_created", "traces", ["workspace_id", "created_at"], unique=False
    )

    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("request_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("request_id")

    op.drop_index("ix_traces_workspace_created", table_name="traces")
    op.drop_index(op.f("ix_traces_message_id"), table_name="traces")
    op.drop_index(op.f("ix_traces_user_id"), table_name="traces")
    op.drop_index(op.f("ix_traces_workspace_id"), table_name="traces")
    op.drop_index(op.f("ix_traces_request_id"), table_name="traces")
    op.drop_table("traces")
