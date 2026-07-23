"""Add one durable display order across valid and rejected WhatsApp contacts.

Revision ID: 0050_whatsapp_roster_order
Revises: 0049_visa_ai_image_jobs
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0050_whatsapp_roster_order"
down_revision = "0049_visa_ai_image_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_broadcast_recipients",
        sa.Column("display_order", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "whatsapp_broadcast_rejected_contacts",
        sa.Column("display_order", sa.BigInteger(), nullable=True),
    )

    # Existing rows predate the shared sequence. Backfill them deterministically
    # without rewriting, deleting, or otherwise changing any recipient data.
    # Exact Excel interleaving cannot be reconstructed for legacy rows, so their
    # creation timestamp plus stable type/id tie-breakers form the best available
    # historical order.
    op.execute(
        """
        WITH ordered AS (
            SELECT
                contact_kind,
                contact_id,
                ROW_NUMBER() OVER (
                    PARTITION BY broadcast_group_id
                    ORDER BY created_at ASC, contact_kind ASC, contact_id ASC
                )::BIGINT AS display_order
            FROM (
                SELECT
                    'recipient'::TEXT AS contact_kind,
                    id AS contact_id,
                    broadcast_group_id,
                    created_at
                FROM whatsapp_broadcast_recipients
                UNION ALL
                SELECT
                    'rejected'::TEXT AS contact_kind,
                    id AS contact_id,
                    broadcast_group_id,
                    created_at
                FROM whatsapp_broadcast_rejected_contacts
            ) AS contacts
        )
        UPDATE whatsapp_broadcast_recipients AS recipients
        SET display_order = ordered.display_order
        FROM ordered
        WHERE ordered.contact_kind = 'recipient'
          AND ordered.contact_id = recipients.id
        """
    )
    op.execute(
        """
        WITH ordered AS (
            SELECT
                contact_kind,
                contact_id,
                ROW_NUMBER() OVER (
                    PARTITION BY broadcast_group_id
                    ORDER BY created_at ASC, contact_kind ASC, contact_id ASC
                )::BIGINT AS display_order
            FROM (
                SELECT
                    'recipient'::TEXT AS contact_kind,
                    id AS contact_id,
                    broadcast_group_id,
                    created_at
                FROM whatsapp_broadcast_recipients
                UNION ALL
                SELECT
                    'rejected'::TEXT AS contact_kind,
                    id AS contact_id,
                    broadcast_group_id,
                    created_at
                FROM whatsapp_broadcast_rejected_contacts
            ) AS contacts
        )
        UPDATE whatsapp_broadcast_rejected_contacts AS rejected
        SET display_order = ordered.display_order
        FROM ordered
        WHERE ordered.contact_kind = 'rejected'
          AND ordered.contact_id = rejected.id
        """
    )

    op.create_index(
        "ix_whatsapp_recipients_group_display_order",
        "whatsapp_broadcast_recipients",
        ["broadcast_group_id", "display_order"],
        unique=False,
    )
    op.create_index(
        "ix_whatsapp_rejected_contacts_group_display_order",
        "whatsapp_broadcast_rejected_contacts",
        ["broadcast_group_id", "display_order"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_whatsapp_rejected_contacts_group_display_order",
        table_name="whatsapp_broadcast_rejected_contacts",
    )
    op.drop_index(
        "ix_whatsapp_recipients_group_display_order",
        table_name="whatsapp_broadcast_recipients",
    )
    op.drop_column(
        "whatsapp_broadcast_rejected_contacts",
        "display_order",
    )
    op.drop_column(
        "whatsapp_broadcast_recipients",
        "display_order",
    )
