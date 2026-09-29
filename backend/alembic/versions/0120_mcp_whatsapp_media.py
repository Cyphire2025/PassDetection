"""Retain scanned WhatsApp header sources and provider-upload attempt receipts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0120_mcp_whatsapp_media"
down_revision = "0119_mcp_contact_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "mcp_whatsapp_header_media",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("original_grant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_grants.id", ondelete="SET NULL")),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("broadcast_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("handle_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("original_storage_key", sa.String(200), nullable=False, unique=True),
        sa.Column("normalized_storage_key", sa.String(200), nullable=False, unique=True),
        sa.Column("original_sha256", sa.String(64), nullable=False),
        sa.Column("normalized_sha256", sa.String(64), nullable=False),
        sa.Column("original_byte_size", sa.BigInteger(), nullable=False),
        sa.Column("normalized_byte_size", sa.BigInteger(), nullable=False),
        sa.Column("filename", sa.String(120), nullable=False),
        sa.Column("original_media_type", sa.String(32), nullable=False),
        sa.Column("normalized_media_type", sa.String(32), nullable=False),
        sa.Column("provider_media_id", sa.String(255)),
        sa.Column("provider_phone_number_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True)),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_expires_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_code", sa.String(80)),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_hash", name="uq_mcp_wa_media_user_key"),
        sa.CheckConstraint("original_byte_size BETWEEN 1 AND 5242880", name="ck_mcp_wa_media_original_size"),
        sa.CheckConstraint("normalized_byte_size BETWEEN 1 AND 5242880", name="ck_mcp_wa_media_normalized_size"),
        sa.CheckConstraint("original_media_type IN ('image/jpeg', 'image/png') AND normalized_media_type IN ('image/jpeg', 'image/png')", name="ck_mcp_wa_media_type"),
        sa.CheckConstraint("status IN ('staged', 'uploading', 'ready', 'failed', 'unknown')", name="ck_mcp_wa_media_status"),
        sa.CheckConstraint("status != 'ready' OR provider_media_id IS NOT NULL", name="ck_mcp_wa_media_ready"),
        sa.CheckConstraint("expires_at > created_at", name="ck_mcp_wa_media_expiry"),
        sa.CheckConstraint("revision >= 1", name="ck_mcp_wa_media_revision"),
        sa.CheckConstraint("(attempt_id IS NULL AND attempted_at IS NULL AND attempt_expires_at IS NULL) OR (attempt_id IS NOT NULL AND attempted_at IS NOT NULL AND attempt_expires_at IS NOT NULL AND attempt_expires_at > attempted_at)", name="ck_mcp_wa_media_attempt"),
    )
    op.create_index("ix_mcp_wa_media_grant_created", "mcp_whatsapp_header_media", ["original_grant_id", "created_at"])
    op.create_index("ix_mcp_wa_media_expiry", "mcp_whatsapp_header_media", ["expires_at"])
    op.create_table(
        "mcp_whatsapp_header_access",
        sa.Column("media_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_whatsapp_header_media.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("grant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_grants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("handle_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE mcp_whatsapp_header_media, mcp_whatsapp_header_access IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM mcp_whatsapp_header_media) OR EXISTS (SELECT 1 FROM mcp_whatsapp_header_access)")).scalar_one():
        raise RuntimeError("MCP WhatsApp media history must be retained; keep the additive schema during recovery.")
    op.drop_table("mcp_whatsapp_header_access")
    op.drop_table("mcp_whatsapp_header_media")
