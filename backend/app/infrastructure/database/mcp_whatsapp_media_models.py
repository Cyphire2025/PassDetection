"""Retained scanned header images and durable provider-upload attempt receipts."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base, _utcnow


class MCPWhatsAppHeaderMediaModel(Base):
    __tablename__ = "mcp_whatsapp_header_media"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_hash", name="uq_mcp_wa_media_user_key"),
        CheckConstraint(
            "original_byte_size BETWEEN 1 AND 5242880", name="ck_mcp_wa_media_original_size"
        ),
        CheckConstraint(
            "normalized_byte_size BETWEEN 1 AND 5242880", name="ck_mcp_wa_media_normalized_size"
        ),
        CheckConstraint(
            "original_media_type IN ('image/jpeg', 'image/png') AND normalized_media_type IN ('image/jpeg', 'image/png')",
            name="ck_mcp_wa_media_type",
        ),
        CheckConstraint(
            "status IN ('staged', 'uploading', 'ready', 'failed', 'unknown')",
            name="ck_mcp_wa_media_status",
        ),
        CheckConstraint(
            "status != 'ready' OR provider_media_id IS NOT NULL", name="ck_mcp_wa_media_ready"
        ),
        CheckConstraint("expires_at > created_at", name="ck_mcp_wa_media_expiry"),
        CheckConstraint("revision >= 1", name="ck_mcp_wa_media_revision"),
        CheckConstraint(
            "(attempt_id IS NULL AND attempted_at IS NULL AND attempt_expires_at IS NULL) OR (attempt_id IS NOT NULL AND attempted_at IS NOT NULL AND attempt_expires_at IS NOT NULL AND attempt_expires_at > attempted_at)",
            name="ck_mcp_wa_media_attempt",
        ),
        Index("ix_mcp_wa_media_grant_created", "original_grant_id", "created_at"),
        Index("ix_mcp_wa_media_expiry", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    original_grant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mcp_grants.id", ondelete="SET NULL")
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"))
    broadcast_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE")
    )
    idempotency_hash: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    handle_hash: Mapped[str] = mapped_column(String(64), unique=True)
    original_storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    normalized_storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    original_sha256: Mapped[str] = mapped_column(String(64))
    normalized_sha256: Mapped[str] = mapped_column(String(64))
    original_byte_size: Mapped[int] = mapped_column(BigInteger)
    normalized_byte_size: Mapped[int] = mapped_column(BigInteger)
    filename: Mapped[str] = mapped_column(String(120))
    original_media_type: Mapped[str] = mapped_column(String(32))
    normalized_media_type: Mapped[str] = mapped_column(String(32))
    provider_media_id: Mapped[str | None] = mapped_column(String(255))
    provider_phone_number_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="staged")
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    revision: Mapped[int] = mapped_column(Integer, default=1)


class MCPWhatsAppHeaderAccessModel(Base):
    """Grant-specific locators; recovery retains the original upload provenance."""

    __tablename__ = "mcp_whatsapp_header_access"

    media_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mcp_whatsapp_header_media.id", ondelete="CASCADE"),
        primary_key=True,
    )
    grant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mcp_grants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    handle_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
