"""P11-S14: per-document knowledge index mode.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "index_mode", sa.String(length=20), nullable=False, server_default="hybrid"
        ),
    )
    op.create_index("ix_documents_index_mode", "documents", ["index_mode"])


def downgrade() -> None:
    op.drop_index("ix_documents_index_mode", table_name="documents")
    op.drop_column("documents", "index_mode")