"""Add durable receipts for resumable document upload chunks.

Revision ID: 0067_document_upload_chunks
Revises: 0066_storage_cleanup_jobs
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0067_document_upload_chunks"
down_revision = "0066_storage_cleanup_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_upload_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("upload_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow", sa.String(length=32), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_type", sa.String(length=32), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("expected_chunk_count", sa.Integer(), nullable=False),
        sa.Column("expected_file_count", sa.Integer(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("byte_count", sa.BigInteger(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("accepted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rejected_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "rejected_documents",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("chunk_index >= 0", name="ck_document_upload_chunks_index"),
        sa.CheckConstraint(
            "chunk_index < expected_chunk_count",
            name="ck_document_upload_chunks_index_manifest",
        ),
        sa.CheckConstraint(
            "expected_chunk_count BETWEEN 1 AND 1500",
            name="ck_document_upload_chunks_expected_chunks",
        ),
        sa.CheckConstraint(
            "expected_file_count BETWEEN 1 AND 1500",
            name="ck_document_upload_chunks_expected_files",
        ),
        sa.CheckConstraint(
            "expected_file_count >= expected_chunk_count "
            "AND expected_file_count <= expected_chunk_count * 50",
            name="ck_document_upload_chunks_manifest_capacity",
        ),
        sa.CheckConstraint(
            "file_count BETWEEN 1 AND 50",
            name="ck_document_upload_chunks_file_count",
        ),
        sa.CheckConstraint(
            "byte_count BETWEEN 1 AND 67108864",
            name="ck_document_upload_chunks_byte_count",
        ),
        sa.CheckConstraint(
            "accepted_count >= 0 AND rejected_count >= 0 "
            "AND accepted_count + rejected_count = file_count",
            name="ck_document_upload_chunks_result_counts",
        ),
        sa.CheckConstraint(
            "workflow IN ('rename', 'distribution')",
            name="ck_document_upload_chunks_workflow",
        ),
        sa.CheckConstraint(
            "(workflow = 'rename' AND group_id IS NULL AND document_type IS NULL) "
            "OR (workflow = 'distribution' AND group_id IS NOT NULL "
            "AND document_type IN ('visa', 'flight_ticket', 'other'))",
            name="ck_document_upload_chunks_scope",
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["client_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow",
            "upload_id",
            "chunk_index",
            name="uq_document_upload_chunks_workflow_upload_index",
        ),
    )
    op.create_index(
        "ix_document_upload_chunks_scope",
        "document_upload_chunks",
        ["agency_id", "workflow", "upload_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_upload_chunks_scope",
        table_name="document_upload_chunks",
    )
    op.drop_table("document_upload_chunks")
