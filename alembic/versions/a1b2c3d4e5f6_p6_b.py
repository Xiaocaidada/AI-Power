"""p6-b attachments, knowledge metadata, multi-kb

Revision ID: a1b2c3d4e5f6
Revises: f4a5b6c7d8e9
Create Date: 2026-11-22
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_bases") as batch:
        batch.add_column(
            sa.Column("description", sa.String(length=500), nullable=False, server_default="")
        )
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))

    op.create_table(
        "chat_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="document"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ready"),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_attachments_workspace_id", "chat_attachments", ["workspace_id"])
    op.create_index("ix_chat_attachments_user_id", "chat_attachments", ["user_id"])
    op.create_index(
        "ix_chat_attachments_conversation_id", "chat_attachments", ["conversation_id"]
    )
    op.create_index("ix_chat_attachments_message_id", "chat_attachments", ["message_id"])
    op.create_index(
        "ix_chat_attachments_workspace_conversation",
        "chat_attachments",
        ["workspace_id", "conversation_id"],
    )

    op.create_table(
        "conversation_knowledge_bases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "kb_id",
            name="uq_conversation_knowledge_bases_pair",
        ),
    )
    op.create_index(
        "ix_conversation_knowledge_bases_conversation_id",
        "conversation_knowledge_bases",
        ["conversation_id"],
    )
    op.create_index(
        "ix_conversation_knowledge_bases_kb_id",
        "conversation_knowledge_bases",
        ["kb_id"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint(
            "usage_events_message_id_fkey", "usage_events", type_="foreignkey"
        )
        op.create_foreign_key(
            "usage_events_message_id_fkey",
            "usage_events",
            "messages",
            ["message_id"],
            ["id"],
            ondelete="SET NULL",
        )
        rows = bind.execute(
            sa.text("SELECT id, kb_id FROM conversations WHERE kb_id IS NOT NULL")
        ).fetchall()
        for conversation_id, kb_id in rows:
            bind.execute(
                sa.text(
                    "INSERT INTO conversation_knowledge_bases "
                    "(id, conversation_id, kb_id, created_at) "
                    "VALUES (:id, :conversation_id, :kb_id, CURRENT_TIMESTAMP) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "id": uuid4(),
                    "conversation_id": conversation_id,
                    "kb_id": kb_id,
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint(
            "usage_events_message_id_fkey", "usage_events", type_="foreignkey"
        )
        op.create_foreign_key(
            "usage_events_message_id_fkey",
            "usage_events",
            "messages",
            ["message_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.drop_index(
        "ix_conversation_knowledge_bases_kb_id",
        table_name="conversation_knowledge_bases",
    )
    op.drop_index(
        "ix_conversation_knowledge_bases_conversation_id",
        table_name="conversation_knowledge_bases",
    )
    op.drop_table("conversation_knowledge_bases")
    op.drop_index(
        "ix_chat_attachments_workspace_conversation", table_name="chat_attachments"
    )
    op.drop_index("ix_chat_attachments_message_id", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_conversation_id", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_user_id", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_workspace_id", table_name="chat_attachments")
    op.drop_table("chat_attachments")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("tags")
    with op.batch_alter_table("knowledge_bases") as batch:
        batch.drop_column("description")