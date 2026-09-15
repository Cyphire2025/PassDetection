"""Durable verified WhatsApp receipt inbox and immutable attempt bindings.

Revision ID: 0094_whatsapp_receipt_inbox
Revises: 0093_phone_welcome
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0094_whatsapp_receipt_inbox"
down_revision = "0093_phone_welcome"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_provider_message_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_phone_number_id", sa.String(255), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_attempt_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "agency_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agencies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider_phone_number_id", "provider_message_id", name="uq_wa_binding_provider"
        ),
        sa.UniqueConstraint(
            "source_kind", "source_id", "source_attempt_key", name="uq_wa_binding_attempt"
        ),
        sa.CheckConstraint(
            "source_kind IN ('broadcast','traveller_welcome','document','qr','otp')",
            name="ck_wa_binding_source",
        ),
    )
    op.create_index(
        "ix_wa_binding_message", "whatsapp_provider_message_bindings", ["provider_message_id"]
    )
    op.create_index("ix_wa_binding_created", "whatsapp_provider_message_bindings", ["created_at"])
    op.create_table(
        "whatsapp_provider_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("dedupe_key", sa.String(64), nullable=False, unique=True),
        sa.Column("provider_phone_number_id", sa.String(255), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=False),
        sa.Column("provider_status", sa.String(32), nullable=False),
        sa.Column("provider_status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column(
            "binding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("whatsapp_provider_message_bindings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("processing_error_code", sa.String(64), nullable=True),
        sa.CheckConstraint(
            "provider_status IN ('sent','delivered','read','failed')", name="ck_wa_receipt_status"
        ),
        sa.CheckConstraint(
            "state IN ('pending','applied','superseded','source_missing','conflict','expired')",
            name="ck_wa_receipt_state",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_wa_receipt_attempts"),
    )
    op.create_index(
        "ix_wa_receipt_due",
        "whatsapp_provider_receipts",
        ["state", "next_attempt_at", "received_at"],
    )
    op.create_index(
        "ix_wa_receipt_provider",
        "whatsapp_provider_receipts",
        ["provider_phone_number_id", "provider_message_id"],
    )
    op.create_index("ix_wa_receipt_retention", "whatsapp_provider_receipts", ["received_at"])
    op.create_index(
        "ix_whatsapp_provider_receipts_binding_id", "whatsapp_provider_receipts", ["binding_id"]
    )
    # Legacy bindings are resolved lazily, solely by an unambiguous stored
    # provider ID. Never backfill from today's roster phone or current settings.
    op.create_index(
        "ix_whatsapp_message_logs_provider_id", "whatsapp_message_logs", ["provider_message_id"]
    )
    op.create_index(
        "ix_mobile_otp_provider_reference", "mobile_otp_challenges", ["provider_reference"]
    )


def downgrade() -> None:
    op.drop_index("ix_mobile_otp_provider_reference", table_name="mobile_otp_challenges")
    op.drop_index("ix_whatsapp_message_logs_provider_id", table_name="whatsapp_message_logs")
    op.drop_table("whatsapp_provider_receipts")
    op.drop_table("whatsapp_provider_message_bindings")
