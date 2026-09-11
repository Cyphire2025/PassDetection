"""Phone-scoped welcome prerequisites and independent traveller welcome outbox.

Revision ID: 0093_phone_welcome
Revises: 0092_whatsapp_matching_fields
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0093_phone_welcome"
down_revision = "0092_whatsapp_matching_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_message_logs", sa.Column("normalized_phone_number", sa.String(32), nullable=True)
    )
    op.create_table(
        "whatsapp_phone_welcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agency_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agencies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("normalized_phone_number", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_kind", sa.String(16), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "agency_id", "normalized_phone_number", name="uq_whatsapp_phone_welcome"
        ),
    )
    op.create_table(
        "whatsapp_phone_welcome_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "agency_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agencies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("client_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "broadcast_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("passenger_ids", postgresql.JSONB(), nullable=False),
        sa.Column("normalized_phone_number", sa.String(32), nullable=False),
        sa.Column("recipient_name", sa.String(255), nullable=True),
        sa.Column("template_name", sa.String(255), nullable=False),
        sa.Column("rendered_message", sa.Text(), nullable=False),
        sa.Column("header_parameter_values", postgresql.JSONB(), nullable=False),
        sa.Column("template_parameter_values", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("provider_status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_phone_welcome_attempt_batch_status",
        "whatsapp_phone_welcome_attempts",
        ["batch_id", "status"],
    )
    op.create_index(
        "ix_whatsapp_phone_welcome_attempts_provider_message_id",
        "whatsapp_phone_welcome_attempts",
        ["provider_message_id"],
    )
    # Phone correction clears state.batch_id. Only a matching current attempt
    # can safely establish an immutable legacy destination. Historical logs
    # joined directly to today's recipient phone are deliberately excluded.
    op.execute("""
        UPDATE whatsapp_message_logs AS logs
        SET normalized_phone_number = recipients.normalized_phone_number
        FROM whatsapp_recipient_message_states AS states,
             whatsapp_broadcast_recipients AS recipients
        WHERE states.recipient_id = recipients.id
          AND states.agency_id = recipients.agency_id
          AND states.batch_id IS NOT NULL
          AND logs.batch_id = states.batch_id
          AND logs.recipient_id = states.recipient_id
          AND logs.agency_id = states.agency_id
          AND logs.message_type = states.message_type
    """)
    op.execute("""
        INSERT INTO whatsapp_phone_welcomes
            (id, agency_id, normalized_phone_number, status, attempt_id, attempt_kind,
             delivered_at, provider_status_at, status_updated_at, created_at, updated_at)
        SELECT DISTINCT ON (logs.agency_id, logs.normalized_phone_number)
            logs.id, logs.agency_id, logs.normalized_phone_number, logs.status,
            logs.id, 'broadcast',
            CASE WHEN logs.status IN ('delivered', 'read')
                THEN COALESCE(logs.provider_status_at, logs.status_updated_at) END,
            logs.provider_status_at, logs.status_updated_at, logs.created_at, now()
        FROM whatsapp_message_logs AS logs
        WHERE logs.message_type = 'welcome' AND logs.normalized_phone_number IS NOT NULL
          AND logs.status IN ('queued','processing','submitted','sent','delivered','read','delivery_unknown')
        ORDER BY logs.agency_id, logs.normalized_phone_number,
            CASE logs.status WHEN 'read' THEN 7 WHEN 'delivered' THEN 6
                WHEN 'sent' THEN 5 WHEN 'submitted' THEN 4
                WHEN 'delivery_unknown' THEN 3 WHEN 'processing' THEN 2 ELSE 1 END DESC,
            logs.status_updated_at DESC, logs.id
    """)


def downgrade() -> None:
    op.drop_table("whatsapp_phone_welcome_attempts")
    op.drop_table("whatsapp_phone_welcomes")
    op.drop_column("whatsapp_message_logs", "normalized_phone_number")
