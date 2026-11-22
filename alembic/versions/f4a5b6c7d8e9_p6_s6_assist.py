"""p6 prompt library and assist

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-11-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4a5b6c7d8e9"
down_revision: str | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("prompt_templates", recreate="auto") as batch:
        batch.add_column(
            sa.Column(
                "category",
                sa.String(length=50),
                nullable=False,
                server_default="general",
            )
        )
    op.create_index(
        op.f("ix_prompt_templates_category"),
        "prompt_templates",
        ["category"],
        unique=False,
    )

    op.create_table(
        "prompt_favorites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["prompt_templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "user_id", name="uq_prompt_favorites_template_user"),
    )
    op.create_index(
        op.f("ix_prompt_favorites_template_id"),
        "prompt_favorites",
        ["template_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_favorites_user_id"),
        "prompt_favorites",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_prompt_favorites_user_id"), table_name="prompt_favorites")
    op.drop_index(op.f("ix_prompt_favorites_template_id"), table_name="prompt_favorites")
    op.drop_table("prompt_favorites")

    op.drop_index(op.f("ix_prompt_templates_category"), table_name="prompt_templates")
    with op.batch_alter_table("prompt_templates", recreate="auto") as batch:
        batch.drop_column("category")