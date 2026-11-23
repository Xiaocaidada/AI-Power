"""p8 agent builder sessions

Revision ID: f60718293041
Revises: e5f607182930
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f60718293041"
down_revision: str | None = "e5f607182930"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_builder_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_id", sa.Uuid(), nullable=True),
        sa.Column("provider_id", sa.String(50), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("draft_definition", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_agent_builder_sessions_workspace_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_agent_builder_sessions_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["custom_agents.id"],
            name="fk_agent_builder_sessions_agent_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name="fk_agent_builder_sessions_workflow_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_builder_sessions_workspace_id",
        "agent_builder_sessions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_agent_builder_sessions_user_id",
        "agent_builder_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_agent_builder_sessions_agent_id",
        "agent_builder_sessions",
        ["agent_id"],
    )
    op.create_index(
        "ix_agent_builder_sessions_workspace_updated",
        "agent_builder_sessions",
        ["workspace_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_builder_sessions_workspace_updated",
        table_name="agent_builder_sessions",
    )
    op.drop_index(
        "ix_agent_builder_sessions_agent_id", table_name="agent_builder_sessions"
    )
    op.drop_index(
        "ix_agent_builder_sessions_user_id", table_name="agent_builder_sessions"
    )
    op.drop_index(
        "ix_agent_builder_sessions_workspace_id", table_name="agent_builder_sessions"
    )
    op.drop_table("agent_builder_sessions")