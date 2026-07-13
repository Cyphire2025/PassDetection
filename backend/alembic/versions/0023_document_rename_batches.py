"""Add document rename batches.

Revision ID: 0023_document_rename_batches
Revises: 0022_document_distribution
Create Date: 2026-07-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0023_document_rename_batches"
down_revision = "0022_document_distribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_rename_batches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("visa_count", sa.Integer(), nullable=False),
        sa.Column("ticket_count", sa.Integer(), nullable=False),
        sa.Column("unknown_count", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_rename_batches_agency_id", "document_rename_batches", ["agency_id"])
    op.create_index("ix_document_rename_batches_status", "document_rename_batches", ["status"])

    op.create_table(
        "document_rename_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("renamed_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("detected_type", sa.String(length=32), nullable=False),
        sa.Column("extracted_name", sa.String(length=255), nullable=True),
        sa.Column("extracted_passport_number", sa.String(length=32), nullable=True),
        sa.Column("extracted_reference", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["document_rename_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_rename_items_batch_id", "document_rename_items", ["batch_id"])
    op.create_index("ix_document_rename_items_agency_id", "document_rename_items", ["agency_id"])
    op.create_index("ix_document_rename_items_detected_type", "document_rename_items", ["detected_type"])
    op.create_index("ix_document_rename_items_status", "document_rename_items", ["status"])
    op.create_index("ix_document_rename_items_batch_created", "document_rename_items", ["batch_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_document_rename_items_batch_created", table_name="document_rename_items")
    op.drop_index("ix_document_rename_items_status", table_name="document_rename_items")
    op.drop_index("ix_document_rename_items_detected_type", table_name="document_rename_items")
    op.drop_index("ix_document_rename_items_agency_id", table_name="document_rename_items")
    op.drop_index("ix_document_rename_items_batch_id", table_name="document_rename_items")
    op.drop_table("document_rename_items")
    op.drop_index("ix_document_rename_batches_status", table_name="document_rename_batches")
    op.drop_index("ix_document_rename_batches_agency_id", table_name="document_rename_batches")
    op.drop_table("document_rename_batches")
