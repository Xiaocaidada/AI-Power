"""p8 s5c review, loop, http/mcp, memory, ratings and reports

Revision ID: c93a4b5d6e70
Revises: a71829304152
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c93a4b5d6e70"
down_revision: str | None = "a71829304152"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("node_run_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name="fk_workflow_reviews_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["node_run_id"],
            ["workflow_node_runs.id"],
            name="fk_workflow_reviews_node_run_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_workflow_reviews_workspace_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"],
            ["users.id"],
            name="fk_workflow_reviews_reviewer_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_reviews_run_id", "workflow_reviews", ["run_id"])
    op.create_index(
        "ix_workflow_reviews_workspace_id", "workflow_reviews", ["workspace_id"]
    )
    op.create_index("ix_workflow_reviews_status", "workflow_reviews", ["status"])
    op.create_index(
        "ix_workflow_reviews_workspace_status",
        "workflow_reviews",
        ["workspace_id", "status", "created_at"],
    )

    op.create_table(
        "agent_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_agent_memories_workspace_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_agent_memories_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["custom_agents.id"],
            name="fk_agent_memories_agent_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_memories_workspace_id", "agent_memories", ["workspace_id"])
    op.create_index("ix_agent_memories_user_id", "agent_memories", ["user_id"])
    op.create_index("ix_agent_memories_agent_id", "agent_memories", ["agent_id"])
    op.create_index("ix_agent_memories_scope", "agent_memories", ["scope"])
    op.create_index(
        "ix_agent_memories_workspace_user_updated",
        "agent_memories",
        ["workspace_id", "user_id", "updated_at"],
    )

    op.create_table(
        "agent_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["custom_agents.id"],
            name="fk_agent_reviews_agent_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_agent_reviews_workspace_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_agent_reviews_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "user_id", name="uq_agent_reviews_agent_user"),
    )
    op.create_index("ix_agent_reviews_agent_id", "agent_reviews", ["agent_id"])
    op.create_index("ix_agent_reviews_workspace_id", "agent_reviews", ["workspace_id"])
    op.create_index("ix_agent_reviews_user_id", "agent_reviews", ["user_id"])
    op.create_index("ix_agent_reviews_status", "agent_reviews", ["status"])
    op.create_index(
        "ix_agent_reviews_agent_status",
        "agent_reviews",
        ["agent_id", "status", "created_at"],
    )

    op.create_table(
        "agent_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("reporter_user_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("handled_by", sa.Uuid(), nullable=True),
        sa.Column("resolution", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["custom_agents.id"],
            name="fk_agent_reports_agent_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reporter_user_id"],
            ["users.id"],
            name="fk_agent_reports_reporter_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["handled_by"],
            ["users.id"],
            name="fk_agent_reports_handled_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_reports_agent_id", "agent_reports", ["agent_id"])
    op.create_index(
        "ix_agent_reports_reporter_user_id", "agent_reports", ["reporter_user_id"]
    )
    op.create_index("ix_agent_reports_status", "agent_reports", ["status"])

    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("endpoint_url", sa.String(1000), nullable=False),
        sa.Column("auth_token_encrypted", sa.Text(), nullable=False),
        sa.Column("auth_hint", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_mcp_servers_name"),
    )
    op.create_index("ix_mcp_servers_enabled", "mcp_servers", ["enabled"])

    with op.batch_alter_table("custom_agents") as batch:
        batch.add_column(
            sa.Column(
                "memory_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(
            sa.Column("rating_avg", sa.Float(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("custom_agents") as batch:
        batch.drop_column("rating_count")
        batch.drop_column("rating_avg")
        batch.drop_column("memory_enabled")

    op.drop_index("ix_mcp_servers_enabled", table_name="mcp_servers")
    op.drop_table("mcp_servers")

    op.drop_index("ix_agent_reports_status", table_name="agent_reports")
    op.drop_index(
        "ix_agent_reports_reporter_user_id", table_name="agent_reports"
    )
    op.drop_index("ix_agent_reports_agent_id", table_name="agent_reports")
    op.drop_table("agent_reports")

    op.drop_index("ix_agent_reviews_agent_status", table_name="agent_reviews")
    op.drop_index("ix_agent_reviews_status", table_name="agent_reviews")
    op.drop_index("ix_agent_reviews_user_id", table_name="agent_reviews")
    op.drop_index("ix_agent_reviews_workspace_id", table_name="agent_reviews")
    op.drop_index("ix_agent_reviews_agent_id", table_name="agent_reviews")
    op.drop_table("agent_reviews")

    op.drop_index(
        "ix_agent_memories_workspace_user_updated", table_name="agent_memories"
    )
    op.drop_index("ix_agent_memories_scope", table_name="agent_memories")
    op.drop_index("ix_agent_memories_agent_id", table_name="agent_memories")
    op.drop_index("ix_agent_memories_user_id", table_name="agent_memories")
    op.drop_index("ix_agent_memories_workspace_id", table_name="agent_memories")
    op.drop_table("agent_memories")

    op.drop_index(
        "ix_workflow_reviews_workspace_status", table_name="workflow_reviews"
    )
    op.drop_index("ix_workflow_reviews_status", table_name="workflow_reviews")
    op.drop_index("ix_workflow_reviews_workspace_id", table_name="workflow_reviews")
    op.drop_index("ix_workflow_reviews_run_id", table_name="workflow_reviews")
    op.drop_table("workflow_reviews")