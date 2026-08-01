"""Raise durable document upload chunk constraints to 50 files.

Revision ID: 0068_document_chunk_limits
Revises: 0067_document_upload_chunks
"""

from __future__ import annotations

from alembic import op

revision = "0068_document_chunk_limits"
down_revision = "0067_document_upload_chunks"
branch_labels = None
depends_on = None


_TABLE_NAME = "document_upload_chunks"
_MANIFEST_CONSTRAINT = "ck_document_upload_chunks_manifest_capacity"
_FILE_COUNT_CONSTRAINT = "ck_document_upload_chunks_file_count"


def upgrade() -> None:
    """Replace only the two restrictive checks; existing rows are preserved."""

    op.drop_constraint(_MANIFEST_CONSTRAINT, _TABLE_NAME, type_="check")
    op.drop_constraint(_FILE_COUNT_CONSTRAINT, _TABLE_NAME, type_="check")
    op.create_check_constraint(
        _MANIFEST_CONSTRAINT,
        _TABLE_NAME,
        "expected_file_count >= expected_chunk_count "
        "AND expected_file_count <= expected_chunk_count * 50",
    )
    op.create_check_constraint(
        _FILE_COUNT_CONSTRAINT,
        _TABLE_NAME,
        "file_count BETWEEN 1 AND 50",
    )


def downgrade() -> None:
    op.drop_constraint(_MANIFEST_CONSTRAINT, _TABLE_NAME, type_="check")
    op.drop_constraint(_FILE_COUNT_CONSTRAINT, _TABLE_NAME, type_="check")
    op.create_check_constraint(
        _MANIFEST_CONSTRAINT,
        _TABLE_NAME,
        "expected_file_count >= expected_chunk_count "
        "AND expected_file_count <= expected_chunk_count * 25",
    )
    op.create_check_constraint(
        _FILE_COUNT_CONSTRAINT,
        _TABLE_NAME,
        "file_count BETWEEN 1 AND 25",
    )
