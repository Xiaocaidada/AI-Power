"""p9 s5 document folders, metadata and url source

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5c6d7e8f9a0"
down_revision: str | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(
            sa.Column("folder", sa.String(255), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column(
                "doc_metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.add_column(sa.Column("source_url", sa.String(1000), nullable=True))
    op.create_index("ix_documents_folder", "documents", ["folder"])


def downgrade() -> None:
    op.drop_index("ix_documents_folder", table_name="documents")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("source_url")
        batch.drop_column("doc_metadata")
        batch.drop_column("folder")