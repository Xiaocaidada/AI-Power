"""p6 projects and conversation workspace

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-11-23 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("default_provider_id", sa.String(length=50), nullable=True),
        sa.Column("default_model", sa.String(length=200), nullable=True),
        sa.Column("default_kb_id", sa.Uuid(), nullable=True),
        sa.Column("default_agent", sa.Boolean(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["default_kb_id"], ["knowledge_bases.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_workspace_id"), "projects", ["workspace_id"], unique=False)
    op.create_index(
        op.f("ix_projects_owner_user_id"), "projects", ["owner_user_id"], unique=False
    )
    op.create_index(
        "ix_projects_workspace_archived", "projects", ["workspace_id", "archived_at"], unique=False
    )

    with op.batch_alter_table("conversations", recreate="auto") as batch:
        batch.add_column(sa.Column("project_id", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column(
                "generation_settings",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch.create_foreign_key(
            "fk_conversations_project_id",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.execute("UPDATE conversations SET updated_at = created_at")
    op.create_index(
        op.f("ix_conversations_project_id"), "conversations", ["project_id"], unique=False
    )
    op.create_index(
        "ix_conversations_workspace_project_archived",
        "conversations",
        ["workspace_id", "project_id", "archived_at"],
        unique=False,
    )
    op.create_index(
        "ix_conversations_workspace_pinned",
        "conversations",
        ["workspace_id", "pinned"],
        unique=False,
    )

    with op.batch_alter_table("messages", recreate="auto") as batch:
        batch.add_column(sa.Column("reply_to_message_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_messages_reply_to_message_id",
            "messages",
            ["reply_to_message_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "message_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "user_id", name="uq_message_feedback_message_user"),
    )
    op.create_index(
        op.f("ix_message_feedback_message_id"), "message_feedback", ["message_id"], unique=False
    )
    op.create_index(
        op.f("ix_message_feedback_user_id"), "message_feedback", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_message_feedback_user_id"), table_name="message_feedback")
    op.drop_index(op.f("ix_message_feedback_message_id"), table_name="message_feedback")
    op.drop_table("message_feedback")

    with op.batch_alter_table("messages", recreate="auto") as batch:
        batch.drop_constraint("fk_messages_reply_to_message_id", type_="foreignkey")
        batch.drop_column("reply_to_message_id")

    op.drop_index("ix_conversations_workspace_pinned", table_name="conversations")
    op.drop_index("ix_conversations_workspace_project_archived", table_name="conversations")
    op.drop_index(op.f("ix_conversations_project_id"), table_name="conversations")
    with op.batch_alter_table("conversations", recreate="auto") as batch:
        batch.drop_constraint("fk_conversations_project_id", type_="foreignkey")
        batch.drop_column("updated_at")
        batch.drop_column("generation_settings")
        batch.drop_column("pinned")
        batch.drop_column("project_id")

    op.drop_index("ix_projects_workspace_archived", table_name="projects")
    op.drop_index(op.f("ix_projects_owner_user_id"), table_name="projects")
    op.drop_index(op.f("ix_projects_workspace_id"), table_name="projects")
    op.drop_table("projects")