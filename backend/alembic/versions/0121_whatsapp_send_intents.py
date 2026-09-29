"""Retain website send intent receipts and their durable broker publication state."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0121_whatsapp_send_intents"
down_revision = "0120_mcp_whatsapp_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "whatsapp_send_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("broadcast_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("initial_response", postgresql.JSONB(), nullable=False),
        sa.Column("worker_payload", postgresql.JSONB(), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), unique=True),
        sa.Column("publication_status", sa.String(16), nullable=False),
        sa.Column("publication_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_hash", name="uq_whatsapp_send_intent_actor_key"),
        sa.CheckConstraint("publication_status IN ('no_batch','pending','published','completed','blocked')", name="ck_whatsapp_send_intent_publication_status"),
        sa.CheckConstraint("publication_attempts >= 0", name="ck_whatsapp_send_intent_attempts"),
    )
    op.create_index("ix_whatsapp_send_intents_due", "whatsapp_send_intents", ["publication_status", "next_attempt_at"])
    op.create_index("ix_whatsapp_send_intents_actor_created", "whatsapp_send_intents", ["user_id", "created_at"])


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE whatsapp_send_intents IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM whatsapp_send_intents)")).scalar_one():
        raise RuntimeError("WhatsApp send intent history must be retained; keep the additive schema during recovery.")
    op.drop_table("whatsapp_send_intents")
