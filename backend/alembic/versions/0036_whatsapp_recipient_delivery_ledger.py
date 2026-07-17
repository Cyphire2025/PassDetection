"""Add durable WhatsApp recipient delivery ledger and soft removal.

Revision ID: 0036_whatsapp_delivery
Revises: 0035_post_submit_verify
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0036_whatsapp_delivery"
down_revision = "0035_post_submit_verify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_broadcast_recipients",
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column(
        "whatsapp_message_logs",
        "message_type",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.add_column(
        "whatsapp_message_logs",
        sa.Column("provider_status_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "whatsapp_recipient_message_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("broadcast_group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["broadcast_group_id"],
            ["whatsapp_broadcast_groups.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["whatsapp_broadcast_recipients.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recipient_id",
            "message_type",
            name="uq_whatsapp_recipient_message_state",
        ),
    )
    op.create_index(
        "ix_whatsapp_recipient_message_states_agency_id",
        "whatsapp_recipient_message_states",
        ["agency_id"],
    )
    op.create_index(
        "ix_whatsapp_recipient_message_states_batch_id",
        "whatsapp_recipient_message_states",
        ["batch_id"],
    )
    op.create_index(
        "ix_whatsapp_recipient_message_states_broadcast_group_id",
        "whatsapp_recipient_message_states",
        ["broadcast_group_id"],
    )
    op.create_index(
        "ix_whatsapp_recipient_message_states_recipient_id",
        "whatsapp_recipient_message_states",
        ["recipient_id"],
    )
    op.create_index(
        "ix_whatsapp_message_states_group_type_status",
        "whatsapp_recipient_message_states",
        ["broadcast_group_id", "message_type", "status"],
    )

    op.execute(
        """
        UPDATE whatsapp_message_logs
        SET
            status = 'failed',
            status_updated_at = now(),
            error_message = COALESCE(
                error_message,
                'Queued delivery expired before provider submission'
            )
        WHERE status = 'queued'
          AND status_updated_at < now() - interval '30 minutes'
        """
    )
    op.execute(
        """
        UPDATE whatsapp_message_logs
        SET
            status = 'delivery_unknown',
            status_updated_at = now(),
            error_message = COALESCE(
                error_message,
                'Delivery outcome is unknown after a worker interruption; '
                'automatic resend is suppressed'
            )
        WHERE status = 'processing'
          AND status_updated_at < now() - interval '30 minutes'
        """
    )

    # Preserve the strongest/latest known outcome from existing logs. Accepted
    # provider submissions suppress future duplicates; failed outcomes remain
    # retryable. Stale processing rows are ambiguous and stay suppressed.
    op.execute(
        """
        WITH ranked AS (
            SELECT DISTINCT ON (recipient_id, message_type)
                id,
                broadcast_group_id,
                recipient_id,
                agency_id,
                message_type,
                status,
                batch_id,
                status_updated_at,
                created_at
            FROM whatsapp_message_logs
            ORDER BY
                recipient_id,
                message_type,
                CASE
                    WHEN status IN ('submitted', 'sent', 'delivered', 'read') THEN 0
                    WHEN status IN ('queued', 'processing', 'delivery_unknown') THEN 1
                    ELSE 2
                END,
                status_updated_at DESC,
                created_at DESC
        )
        INSERT INTO whatsapp_recipient_message_states (
            id,
            broadcast_group_id,
            recipient_id,
            agency_id,
            message_type,
            status,
            batch_id,
            submitted_at,
            status_updated_at,
            provider_status_at,
            created_at,
            updated_at
        )
        SELECT
            id,
            broadcast_group_id,
            recipient_id,
            agency_id,
            message_type,
            CASE
                WHEN status = 'queued'
                     AND status_updated_at < now() - interval '30 minutes'
                    THEN 'failed'
                WHEN status = 'processing'
                     AND status_updated_at < now() - interval '30 minutes'
                    THEN 'delivery_unknown'
                ELSE status
            END,
            CASE
                WHEN status = 'failed' THEN NULL
                WHEN status = 'queued'
                     AND status_updated_at < now() - interval '30 minutes'
                    THEN NULL
                ELSE batch_id
            END,
            CASE
                WHEN status IN ('submitted', 'sent', 'delivered', 'read')
                    THEN created_at
                ELSE NULL
            END,
            status_updated_at,
            NULL,
            created_at,
            status_updated_at
        FROM ranked
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_whatsapp_message_states_group_type_status",
        table_name="whatsapp_recipient_message_states",
    )
    op.drop_index(
        "ix_whatsapp_recipient_message_states_recipient_id",
        table_name="whatsapp_recipient_message_states",
    )
    op.drop_index(
        "ix_whatsapp_recipient_message_states_broadcast_group_id",
        table_name="whatsapp_recipient_message_states",
    )
    op.drop_index(
        "ix_whatsapp_recipient_message_states_batch_id",
        table_name="whatsapp_recipient_message_states",
    )
    op.drop_index(
        "ix_whatsapp_recipient_message_states_agency_id",
        table_name="whatsapp_recipient_message_states",
    )
    op.drop_table("whatsapp_recipient_message_states")
    op.drop_column("whatsapp_message_logs", "provider_status_at")
    op.alter_column(
        "whatsapp_message_logs",
        "message_type",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.drop_column("whatsapp_broadcast_recipients", "removed_at")
