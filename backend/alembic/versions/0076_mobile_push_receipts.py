"""Persist mobile push tickets and provider receipt lifecycle.

Revision ID: 0076_mobile_push_receipts
Revises: 0075_mobile_session_metrics_idx
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0076_mobile_push_receipts"
down_revision = "0075_mobile_session_metrics_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This creates a new, initially empty table. It neither rewrites nor scans
    # mobile_notifications/mobile_push_registrations; referenced-table locks are
    # limited to the CREATE TABLE statement's catalog update.
    op.create_table(
        "mobile_push_deliveries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("notification_id", sa.UUID(), nullable=False),
        sa.Column("registration_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_ticket_id", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="submitting",
            nullable=False,
        ),
        sa.Column("send_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("receipt_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "send_attempts >= 0 AND receipt_attempts >= 0",
            name="ck_mobile_push_delivery_attempts",
        ),
        sa.CheckConstraint(
            "(status = 'delivered' AND delivered_at IS NOT NULL) OR "
            "(status != 'delivered' AND delivered_at IS NULL)",
            name="ck_mobile_push_delivery_delivered_shape",
        ),
        sa.CheckConstraint(
            "(status = 'failed' AND failed_at IS NOT NULL) OR "
            "(status != 'failed' AND failed_at IS NULL)",
            name="ck_mobile_push_delivery_failed_shape",
        ),
        sa.CheckConstraint(
            "provider IN ('expo', 'fcm', 'apns')",
            name="ck_mobile_push_delivery_provider",
        ),
        sa.CheckConstraint(
            "status NOT IN ('receipt_pending', 'delivered') OR "
            "provider_ticket_id IS NOT NULL",
            name="ck_mobile_push_delivery_receipt_shape",
        ),
        sa.CheckConstraint(
            "status IN ('submitting', 'retry', 'receipt_pending', 'delivered', "
            "'failed', 'cancelled')",
            name="ck_mobile_push_delivery_status",
        ),
        sa.CheckConstraint(
            "(provider_ticket_id IS NULL AND submitted_at IS NULL) OR "
            "(provider_ticket_id IS NOT NULL AND submitted_at IS NOT NULL)",
            name="ck_mobile_push_delivery_ticket_shape",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["mobile_notifications.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["registration_id"],
            ["mobile_push_registrations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "notification_id",
            "registration_id",
            name="uq_mobile_push_delivery_target",
        ),
    )
    # The table is empty, so ordinary index creation is immediate and avoids
    # PostgreSQL's CREATE INDEX CONCURRENTLY transaction restriction.
    op.create_index(
        "ix_mobile_push_delivery_due",
        "mobile_push_deliveries",
        ["provider", "status", "next_attempt_at"],
        unique=False,
    )
    op.create_index(
        "ix_mobile_push_delivery_notification",
        "mobile_push_deliveries",
        ["notification_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_mobile_push_delivery_registration",
        "mobile_push_deliveries",
        ["registration_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_mobile_push_delivery_provider_ticket",
        "mobile_push_deliveries",
        ["provider", "provider_ticket_id"],
        unique=True,
        postgresql_where=sa.text("provider_ticket_id IS NOT NULL"),
        sqlite_where=sa.text("provider_ticket_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_mobile_push_delivery_provider_ticket",
        table_name="mobile_push_deliveries",
    )
    op.drop_index(
        "ix_mobile_push_delivery_registration",
        table_name="mobile_push_deliveries",
    )
    op.drop_index(
        "ix_mobile_push_delivery_notification",
        table_name="mobile_push_deliveries",
    )
    op.drop_index(
        "ix_mobile_push_delivery_due",
        table_name="mobile_push_deliveries",
    )
    op.drop_table("mobile_push_deliveries")
