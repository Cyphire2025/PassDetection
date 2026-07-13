"""Add document distribution batches.

Revision ID: 0022_document_distribution
Revises: 0021_family_submissions
Create Date: 2026-07-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0022_document_distribution"
down_revision = "0021_family_submissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_distribution_batches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("uploaded_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("matched_count", sa.Integer(), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["group_id"], ["client_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_distribution_batches_agency_id", "document_distribution_batches", ["agency_id"])
    op.create_index("ix_document_distribution_batches_group_id", "document_distribution_batches", ["group_id"])
    op.create_index("ix_document_distribution_batches_document_type", "document_distribution_batches", ["document_type"])
    op.create_index("ix_document_distribution_batches_status", "document_distribution_batches", ["status"])
    op.create_index(
        "ix_document_batches_group_type_created",
        "document_distribution_batches",
        ["group_id", "document_type", "created_at"],
    )

    op.create_table(
        "distributed_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("passenger_id", sa.UUID(), nullable=True),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("detected_type", sa.String(length=32), nullable=False),
        sa.Column("match_status", sa.String(length=40), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=False),
        sa.Column("match_reason", sa.String(length=255), nullable=True),
        sa.Column("extracted_name", sa.String(length=255), nullable=True),
        sa.Column("extracted_passport_number", sa.String(length=32), nullable=True),
        sa.Column("extracted_reference", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["document_distribution_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["client_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["passenger_id"], ["passport_submissions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_distributed_documents_batch_id", "distributed_documents", ["batch_id"])
    op.create_index("ix_distributed_documents_agency_id", "distributed_documents", ["agency_id"])
    op.create_index("ix_distributed_documents_group_id", "distributed_documents", ["group_id"])
    op.create_index("ix_distributed_documents_passenger_id", "distributed_documents", ["passenger_id"])
    op.create_index("ix_distributed_documents_document_type", "distributed_documents", ["document_type"])
    op.create_index("ix_distributed_documents_match_status", "distributed_documents", ["match_status"])
    op.create_index("ix_distributed_documents_batch_passenger", "distributed_documents", ["batch_id", "passenger_id"])
    op.create_index("ix_distributed_documents_group_type", "distributed_documents", ["group_id", "document_type"])


def downgrade() -> None:
    op.drop_index("ix_distributed_documents_group_type", table_name="distributed_documents")
    op.drop_index("ix_distributed_documents_batch_passenger", table_name="distributed_documents")
    op.drop_index("ix_distributed_documents_match_status", table_name="distributed_documents")
    op.drop_index("ix_distributed_documents_document_type", table_name="distributed_documents")
    op.drop_index("ix_distributed_documents_passenger_id", table_name="distributed_documents")
    op.drop_index("ix_distributed_documents_group_id", table_name="distributed_documents")
    op.drop_index("ix_distributed_documents_agency_id", table_name="distributed_documents")
    op.drop_index("ix_distributed_documents_batch_id", table_name="distributed_documents")
    op.drop_table("distributed_documents")
    op.drop_index("ix_document_batches_group_type_created", table_name="document_distribution_batches")
    op.drop_index("ix_document_distribution_batches_status", table_name="document_distribution_batches")
    op.drop_index("ix_document_distribution_batches_document_type", table_name="document_distribution_batches")
    op.drop_index("ix_document_distribution_batches_group_id", table_name="document_distribution_batches")
    op.drop_index("ix_document_distribution_batches_agency_id", table_name="document_distribution_batches")
    op.drop_table("document_distribution_batches")
