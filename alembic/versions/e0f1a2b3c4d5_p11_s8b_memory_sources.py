"""P11-S8b: authorized workflow and document memory extraction sources.

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e0f1a2b3c4d5"
down_revision: str | Sequence[str] | None = "d9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory_settings",
        sa.Column(
            "allow_workflow_extract", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "memory_settings",
        sa.Column(
            "allow_document_extract", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "workflows",
        sa.Column(
            "memory_extract_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "memory_extract_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "memory_extract_enabled")
    op.drop_column("workflows", "memory_extract_enabled")
    op.drop_column("memory_settings", "allow_document_extract")
    op.drop_column("memory_settings", "allow_workflow_extract")