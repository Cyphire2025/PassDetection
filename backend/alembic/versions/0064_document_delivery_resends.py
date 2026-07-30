"""Allow an explicitly requested WhatsApp resend to retain attempt history.

Revision ID: 0064_document_resends
Revises: 0063_qr_whatsapp
"""

from __future__ import annotations

from alembic import op

revision = "0064_document_resends"
down_revision = "0063_qr_whatsapp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_document_whatsapp_delivery_document",
        "document_whatsapp_deliveries",
        type_="unique",
    )
    # Retire legacy, still-unresolved link-only noise created before links
    # stopped counting as relevance evidence. Candidate-backed or attachment
    # reviews are deliberately left untouched.
    op.execute(
        """
        UPDATE email_review_items reviews
        SET status = 'cancelled',
            resolution_code = 'LINK_ONLY_UNRELATED',
            resolution_notes = 'Automatically retired after relevance policy upgrade',
            deferred_until = NULL,
            resolved_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        FROM email_artifacts artifacts, email_messages messages
        WHERE reviews.artifact_id = artifacts.id
          AND reviews.message_id = messages.id
          AND reviews.agency_id = messages.agency_id
          AND reviews.status IN ('open', 'deferred')
          AND reviews.review_type = 'retrieval'
          AND reviews.candidate_group_id IS NULL
          AND reviews.candidate_passenger_id IS NULL
          AND artifacts.kind IN ('direct_link', 'cloud_link', 'portal_link')
          AND messages.has_attachments = false
        """
    )
    op.execute(
        """
        UPDATE email_artifacts artifacts
        SET retrieval_status = 'ignored',
            processing_status = 'ignored',
            processed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        FROM email_messages messages
        WHERE artifacts.message_id = messages.id
          AND artifacts.agency_id = messages.agency_id
          AND artifacts.kind IN ('direct_link', 'cloud_link', 'portal_link')
          AND messages.has_attachments = false
          AND EXISTS (
            SELECT 1
            FROM email_review_items reviews
            WHERE reviews.artifact_id = artifacts.id
              AND reviews.message_id = messages.id
              AND reviews.agency_id = messages.agency_id
              AND reviews.resolution_code = 'LINK_ONLY_UNRELATED'
          )
        """
    )
    op.execute(
        """
        UPDATE email_messages messages
        SET relevance_status = 'ignored',
            processing_status = 'ignored',
            processed_artifact_count = artifact_count,
            review_count = 0,
            processed_at = COALESCE(processed_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE messages.has_attachments = false
          AND NOT EXISTS (
            SELECT 1
            FROM email_review_items active_reviews
            WHERE active_reviews.message_id = messages.id
              AND active_reviews.agency_id = messages.agency_id
              AND active_reviews.status IN ('open', 'deferred')
          )
          AND EXISTS (
            SELECT 1
            FROM email_artifacts artifacts
            WHERE artifacts.message_id = messages.id
              AND artifacts.agency_id = messages.agency_id
              AND artifacts.kind IN ('direct_link', 'cloud_link', 'portal_link')
              AND EXISTS (
                SELECT 1
                FROM email_review_items reviews
                WHERE reviews.artifact_id = artifacts.id
                  AND reviews.message_id = messages.id
                  AND reviews.agency_id = messages.agency_id
                  AND reviews.resolution_code = 'LINK_ONLY_UNRELATED'
              )
          )
        """
    )


def downgrade() -> None:
    # Keep only the newest attempt for each document before restoring the
    # legacy one-row constraint. Downgrades are operator-initiated and this
    # deterministic cleanup avoids a constraint failure.
    op.execute(
        """
        DELETE FROM document_whatsapp_deliveries older
        USING document_whatsapp_deliveries newer
        WHERE older.distributed_document_id = newer.distributed_document_id
          AND older.distributed_document_id IS NOT NULL
          AND (
            older.created_at < newer.created_at
            OR (
              older.created_at = newer.created_at
              AND older.id::text < newer.id::text
            )
          )
        """
    )
    op.create_unique_constraint(
        "uq_document_whatsapp_delivery_document",
        "document_whatsapp_deliveries",
        ["distributed_document_id"],
    )
