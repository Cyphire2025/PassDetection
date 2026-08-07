"""Allow additive domestic onward and return distribution lanes.

Revision ID: 0080_domestic_ticket_lanes
Revises: 0079_arrival_ticket_distribution
"""

from __future__ import annotations

from alembic import op

revision = "0080_domestic_ticket_lanes"
down_revision = "0079_arrival_ticket_distribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Widen the receipt constraint without updating or deleting existing rows."""

    op.drop_constraint(
        "ck_document_upload_chunks_scope",
        "document_upload_chunks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_document_upload_chunks_scope",
        "document_upload_chunks",
        "(workflow = 'rename' AND group_id IS NULL AND document_type IS NULL) "
        "OR (workflow = 'distribution' AND group_id IS NOT NULL "
        "AND document_type IN "
        "('visa', 'flight_ticket', 'flight_ticket_arrival', "
        "'flight_ticket_domestic', 'flight_ticket_domestic_arrival', 'other'))",
    )


def downgrade() -> None:
    """Restore the legacy constraint only when no domestic receipt still exists.

    PostgreSQL rejects the narrower constraint if domestic receipt rows remain,
    preserving those rows instead of silently relabelling or deleting them.
    """

    op.drop_constraint(
        "ck_document_upload_chunks_scope",
        "document_upload_chunks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_document_upload_chunks_scope",
        "document_upload_chunks",
        "(workflow = 'rename' AND group_id IS NULL AND document_type IS NULL) "
        "OR (workflow = 'distribution' AND group_id IS NOT NULL "
        "AND document_type IN "
        "('visa', 'flight_ticket', 'flight_ticket_arrival', 'other'))",
    )
