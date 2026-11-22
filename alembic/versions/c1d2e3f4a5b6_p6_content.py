"""p6 home placements and announcements

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-11-23 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "b0c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "home_placements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("subtitle", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=False),
        sa.Column("link_url", sa.String(length=500), nullable=False),
        sa.Column("link_label", sa.String(length=50), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_home_placements_kind"), "home_placements", ["kind"], unique=False)
    op.create_index(
        op.f("ix_home_placements_enabled"), "home_placements", ["enabled"], unique=False
    )
    op.create_index(
        "ix_home_placements_kind_enabled", "home_placements", ["kind", "enabled"], unique=False
    )

    op.create_table(
        "announcements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("cover_url", sa.String(length=500), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_announcements_category"), "announcements", ["category"], unique=False)
    op.create_index(op.f("ix_announcements_pinned"), "announcements", ["pinned"], unique=False)
    op.create_index(op.f("ix_announcements_status"), "announcements", ["status"], unique=False)
    op.create_index(
        "ix_announcements_status_published",
        "announcements",
        ["status", "published_at"],
        unique=False,
    )

    op.create_table(
        "announcement_reads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("announcement_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "announcement_id", "user_id", name="uq_announcement_reads_announcement_user"
        ),
    )
    op.create_index(
        op.f("ix_announcement_reads_announcement_id"),
        "announcement_reads",
        ["announcement_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_announcement_reads_user_id"),
        "announcement_reads",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_announcement_reads_user_read",
        "announcement_reads",
        ["user_id", "read_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_announcement_reads_user_read", table_name="announcement_reads")
    op.drop_index(op.f("ix_announcement_reads_user_id"), table_name="announcement_reads")
    op.drop_index(
        op.f("ix_announcement_reads_announcement_id"), table_name="announcement_reads"
    )
    op.drop_table("announcement_reads")

    op.drop_index("ix_announcements_status_published", table_name="announcements")
    op.drop_index(op.f("ix_announcements_status"), table_name="announcements")
    op.drop_index(op.f("ix_announcements_pinned"), table_name="announcements")
    op.drop_index(op.f("ix_announcements_category"), table_name="announcements")
    op.drop_table("announcements")

    op.drop_index("ix_home_placements_kind_enabled", table_name="home_placements")
    op.drop_index(op.f("ix_home_placements_enabled"), table_name="home_placements")
    op.drop_index(op.f("ix_home_placements_kind"), table_name="home_placements")
    op.drop_table("home_placements")