"""Add title to document rename batches.

Revision ID: 0024_document_rename_batch_title
Revises: 0023_document_rename_batches
Create Date: 2026-07-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0024_document_rename_batch_title"
down_revision = "0023_document_rename_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_rename_batches",
        sa.Column("title", sa.String(length=160), server_default="Rename Batch", nullable=False),
    )
    op.alter_column("document_rename_batches", "title", server_default=None)


def downgrade() -> None:
    op.drop_column("document_rename_batches", "title")
