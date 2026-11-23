"""p9 s0 s1 knowledge studio foundation and processing pipeline

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.vector import EmbeddingVector

revision: str = "e2f3a4b5c6d7"
down_revision: str | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workflows") as batch:
        batch.add_column(
            sa.Column(
                "kind", sa.String(30), nullable=False, server_default="agent"
            )
        )
    op.create_index("ix_workflows_kind", "workflows", ["kind"])

    with op.batch_alter_table("workflow_versions") as batch:
        batch.add_column(
            sa.Column(
                "schema_version", sa.Integer(), nullable=False, server_default="1"
            )
        )

    with op.batch_alter_table("workflow_runs") as batch:
        batch.add_column(
            sa.Column(
                "input_payload",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.add_column(
            sa.Column(
                "output_payload",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.add_column(
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True)
        )

    with op.batch_alter_table("knowledge_bases") as batch:
        batch.add_column(
            sa.Column("process_workflow_version_id", sa.Uuid(), nullable=True)
        )
        batch.add_column(
            sa.Column("retrieval_workflow_version_id", sa.Uuid(), nullable=True)
        )
        batch.create_foreign_key(
            "fk_kb_process_workflow_version_id",
            "workflow_versions",
            ["process_workflow_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_kb_retrieval_workflow_version_id",
            "workflow_versions",
            ["retrieval_workflow_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_knowledge_bases_process_workflow_version_id",
        "knowledge_bases",
        ["process_workflow_version_id"],
    )
    op.create_index(
        "ix_knowledge_bases_retrieval_workflow_version_id",
        "knowledge_bases",
        ["retrieval_workflow_version_id"],
    )

    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("process_version_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_documents_process_version_id",
            "workflow_versions",
            ["process_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_documents_process_version_id", "documents", ["process_version_id"]
    )

    op.create_table(
        "workflow_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name="fk_workflow_artifacts_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "node_id", name="uq_workflow_artifacts_run_node"
        ),
    )
    op.create_index(
        "ix_workflow_artifacts_run_id", "workflow_artifacts", ["run_id"]
    )

    op.create_table(
        "knowledge_chunk_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("chunk_meta", sa.JSON(), nullable=False),
        sa.Column("embedding", EmbeddingVector(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name="fk_knowledge_chunk_drafts_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_knowledge_chunk_drafts_workspace_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["kb_id"],
            ["knowledge_bases.id"],
            name="fk_knowledge_chunk_drafts_kb_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_knowledge_chunk_drafts_document_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_chunk_drafts_run_id",
        "knowledge_chunk_drafts",
        ["run_id"],
    )
    op.create_index(
        "ix_knowledge_chunk_drafts_workspace_id",
        "knowledge_chunk_drafts",
        ["workspace_id"],
    )
    op.create_index(
        "ix_knowledge_chunk_drafts_kb_id",
        "knowledge_chunk_drafts",
        ["kb_id"],
    )
    op.create_index(
        "ix_knowledge_chunk_drafts_document_id",
        "knowledge_chunk_drafts",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_chunk_drafts_document_id",
        table_name="knowledge_chunk_drafts",
    )
    op.drop_index(
        "ix_knowledge_chunk_drafts_kb_id", table_name="knowledge_chunk_drafts"
    )
    op.drop_index(
        "ix_knowledge_chunk_drafts_workspace_id",
        table_name="knowledge_chunk_drafts",
    )
    op.drop_index(
        "ix_knowledge_chunk_drafts_run_id", table_name="knowledge_chunk_drafts"
    )
    op.drop_table("knowledge_chunk_drafts")

    op.drop_index("ix_workflow_artifacts_run_id", table_name="workflow_artifacts")
    op.drop_table("workflow_artifacts")

    op.drop_index("ix_documents_process_version_id", table_name="documents")
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint(
            "fk_documents_process_version_id", type_="foreignkey"
        )
        batch.drop_column("process_version_id")

    op.drop_index(
        "ix_knowledge_bases_retrieval_workflow_version_id",
        table_name="knowledge_bases",
    )
    op.drop_index(
        "ix_knowledge_bases_process_workflow_version_id",
        table_name="knowledge_bases",
    )
    with op.batch_alter_table("knowledge_bases") as batch:
        batch.drop_constraint(
            "fk_kb_retrieval_workflow_version_id", type_="foreignkey"
        )
        batch.drop_constraint(
            "fk_kb_process_workflow_version_id", type_="foreignkey"
        )
        batch.drop_column("retrieval_workflow_version_id")
        batch.drop_column("process_workflow_version_id")

    with op.batch_alter_table("workflow_runs") as batch:
        batch.drop_column("applied_at")
        batch.drop_column("output_payload")
        batch.drop_column("input_payload")

    with op.batch_alter_table("workflow_versions") as batch:
        batch.drop_column("schema_version")

    op.drop_index("ix_workflows_kind", table_name="workflows")
    with op.batch_alter_table("workflows") as batch:
        batch.drop_column("kind")