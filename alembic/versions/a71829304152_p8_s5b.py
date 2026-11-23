"""p8 s5b agent plaza and project agents

Revision ID: a71829304152
Revises: f60718293041
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a71829304152"
down_revision: str | None = "f60718293041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("custom_agents") as batch:
        batch.add_column(
            sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.create_index("ix_custom_agents_featured", "custom_agents", ["featured"])

    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("default_custom_agent_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_projects_default_custom_agent_id",
            "custom_agents",
            ["default_custom_agent_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_projects_default_custom_agent_id",
        "projects",
        ["default_custom_agent_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_projects_default_custom_agent_id", table_name="projects")
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint(
            "fk_projects_default_custom_agent_id", type_="foreignkey"
        )
        batch.drop_column("default_custom_agent_id")
    op.drop_index("ix_custom_agents_featured", table_name="custom_agents")
    with op.batch_alter_table("custom_agents") as batch:
        batch.drop_column("featured")