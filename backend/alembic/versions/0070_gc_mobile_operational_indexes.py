"""Add bounded mobile roster and passenger-document lookup indexes.

Revision ID: 0070_mobile_ops_indexes
Revises: 0069_gc_mobile_foundation
"""

from __future__ import annotations

from alembic import op

revision = "0070_mobile_ops_indexes"
down_revision = "0069_gc_mobile_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Both source tables can be large in production. PostgreSQL's ordinary
    # CREATE INDEX blocks writes for the duration of the build, so install the
    # read-path indexes outside Alembic's migration transaction and let normal
    # inserts/updates continue while PostgreSQL performs its two table scans.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_passport_submissions_mobile_roster",
            "passport_submissions",
            ["agency_id", "group_id", "status", "id"],
            unique=False,
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_distributed_documents_mobile_passenger",
            "distributed_documents",
            ["agency_id", "group_id", "passenger_id", "match_status", "document_type"],
            unique=False,
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_distributed_documents_mobile_passenger",
            table_name="distributed_documents",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_passport_submissions_mobile_roster",
            table_name="passport_submissions",
            postgresql_concurrently=True,
        )
