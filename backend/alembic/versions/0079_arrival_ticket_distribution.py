"""Add an independent arrival-ticket document distribution lane.

Revision ID: 0079_arrival_ticket_distribution
Revises: 0078_client_manager_login
"""

from __future__ import annotations

from alembic import op

revision = "0079_arrival_ticket_distribution"
down_revision = "0078_client_manager_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    # A rollback is only safe when no arrival-ticket upload receipt remains.
    # PostgreSQL will reject the narrower check if such rows exist, preserving
    # data instead of deleting or silently relabelling it.
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
        "AND document_type IN ('visa', 'flight_ticket', 'other'))",
    )
