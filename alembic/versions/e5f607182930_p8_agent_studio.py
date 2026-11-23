"""p8 agent studio foundation

Revision ID: e5f607182930
Revises: d4e5f6071829
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f607182930"
down_revision: str | None = "d4e5f6071829"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("custom_agents") as batch:
        batch.add_column(
            sa.Column("mode", sa.String(20), nullable=False, server_default="autonomous")
        )
        batch.add_column(
            sa.Column("icon", sa.String(32), nullable=False, server_default="🤖")
        )
        batch.add_column(
            sa.Column("welcome_message", sa.String(1000), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("examples", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("usage_instructions", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("generation_settings", sa.JSON(), nullable=False, server_default="{}")
        )
        batch.add_column(sa.Column("kb_ids", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(
            sa.Column(
                "workflow_id",
                sa.Uuid(),
                sa.ForeignKey(
                    "workflows.id",
                    name="fk_custom_agents_workflow_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("public_slug", sa.String(80), nullable=True))
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("allow_copy", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(
            sa.Column("show_structure", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(sa.Column("published_snapshot", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("copy_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("favorite_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column(
                "source_agent_id",
                sa.Uuid(),
                sa.ForeignKey(
                    "custom_agents.id",
                    name="fk_custom_agents_source_agent_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch.create_unique_constraint(
            "uq_custom_agents_public_slug", ["public_slug"]
        )

    op.create_index("ix_custom_agents_workflow_id", "custom_agents", ["workflow_id"])
    op.create_index("ix_custom_agents_published", "custom_agents", ["published"])

    op.create_table(
        "agent_favorites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["custom_agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "user_id", name="uq_agent_favorites_agent_user"),
    )
    op.create_index("ix_agent_favorites_agent_id", "agent_favorites", ["agent_id"])
    op.create_index("ix_agent_favorites_user_id", "agent_favorites", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_favorites_user_id", table_name="agent_favorites")
    op.drop_index("ix_agent_favorites_agent_id", table_name="agent_favorites")
    op.drop_table("agent_favorites")
    op.drop_index("ix_custom_agents_published", table_name="custom_agents")
    op.drop_index("ix_custom_agents_workflow_id", table_name="custom_agents")
    with op.batch_alter_table("custom_agents") as batch:
        batch.drop_constraint("uq_custom_agents_public_slug", type_="unique")
        batch.drop_column("source_agent_id")
        batch.drop_column("favorite_count")
        batch.drop_column("copy_count")
        batch.drop_column("usage_count")
        batch.drop_column("published_snapshot")
        batch.drop_column("show_structure")
        batch.drop_column("allow_copy")
        batch.drop_column("published_at")
        batch.drop_column("public_slug")
        batch.drop_column("published")
        batch.drop_column("workflow_id")
        batch.drop_column("kb_ids")
        batch.drop_column("generation_settings")
        batch.drop_column("usage_instructions")
        batch.drop_column("examples")
        batch.drop_column("welcome_message")
        batch.drop_column("icon")
        batch.drop_column("mode")