"""p3 prompt templates

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-21 24:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_prompt_templates_workspace_id"),
        "prompt_templates",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("variables", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["prompt_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "version", name="uq_prompt_versions_template_version"),
    )
    op.create_index(
        op.f("ix_prompt_versions_template_id"),
        "prompt_versions",
        ["template_id"],
        unique=False,
    )

    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("prompt_version_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("system_prompt", sa.Text(), nullable=True))
        batch.create_foreign_key(
            "fk_conversations_prompt_version_id",
            "prompt_versions",
            ["prompt_version_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_constraint("fk_conversations_prompt_version_id", type_="foreignkey")
        batch.drop_column("system_prompt")
        batch.drop_column("prompt_version_id")

    op.drop_index(op.f("ix_prompt_versions_template_id"), table_name="prompt_versions")
    op.drop_table("prompt_versions")
    op.drop_index(op.f("ix_prompt_templates_workspace_id"), table_name="prompt_templates")
    op.drop_table("prompt_templates")
