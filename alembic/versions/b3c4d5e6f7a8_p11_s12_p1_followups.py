"""P11-S12: Agent attachment capability and citation metrics.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "custom_agents",
        sa.Column(
            "attachments_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        "eval_run_items",
        sa.Column("citation_precision", sa.Float(), nullable=True),
    )
    op.add_column(
        "eval_run_items",
        sa.Column("citation_recall", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("eval_run_items", "citation_recall")
    op.drop_column("eval_run_items", "citation_precision")
    op.drop_column("custom_agents", "attachments_enabled")