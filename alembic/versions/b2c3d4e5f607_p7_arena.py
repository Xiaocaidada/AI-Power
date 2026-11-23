"""p7 arena and usage source ref

Revision ID: b2c3d4e5f607
Revises: a1b2c3d4e5f6
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f607"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("usage_events") as batch:
        batch.add_column(sa.Column("source_ref_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_usage_events_source_ref_id",
        "usage_events",
        ["source_ref_id"],
        unique=True,
    )

    op.create_table(
        "arena_rounds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("generation_settings", sa.JSON(), nullable=False),
        sa.Column("blind", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vote_response_id", sa.Uuid(), nullable=True),
        sa.Column("vote_reason", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_arena_rounds_workspace_id", "arena_rounds", ["workspace_id"])
    op.create_index("ix_arena_rounds_user_id", "arena_rounds", ["user_id"])
    op.create_index(
        "ix_arena_rounds_workspace_created",
        "arena_rounds",
        ["workspace_id", "created_at"],
    )

    op.create_table(
        "arena_responses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ttft_ms", sa.Float(), nullable=True),
        sa.Column("total_ms", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["round_id"], ["arena_rounds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "round_id", "position", name="uq_arena_responses_round_position"
        ),
    )
    op.create_index("ix_arena_responses_round_id", "arena_responses", ["round_id"])


def downgrade() -> None:
    op.drop_index("ix_arena_responses_round_id", table_name="arena_responses")
    op.drop_table("arena_responses")
    op.drop_index("ix_arena_rounds_workspace_created", table_name="arena_rounds")
    op.drop_index("ix_arena_rounds_user_id", table_name="arena_rounds")
    op.drop_index("ix_arena_rounds_workspace_id", table_name="arena_rounds")
    op.drop_table("arena_rounds")
    op.drop_index("ix_usage_events_source_ref_id", table_name="usage_events")
    with op.batch_alter_table("usage_events") as batch:
        batch.drop_column("source_ref_id")