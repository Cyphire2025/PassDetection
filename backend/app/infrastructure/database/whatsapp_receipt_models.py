"""Verified provider receipts and write-once links to original send attempts."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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


class WhatsAppProviderMessageBindingModel(Base):
    __tablename__ = "whatsapp_provider_message_bindings"
    __table_args__ = (
        UniqueConstraint(
            "provider_phone_number_id", "provider_message_id", name="uq_wa_binding_provider"
        ),
        UniqueConstraint(
            "source_kind", "source_id", "source_attempt_key", name="uq_wa_binding_attempt"
        ),
        CheckConstraint(
            "source_kind IN ('broadcast','traveller_welcome','document','qr','otp')",
            name="ck_wa_binding_source",
        ),
        Index("ix_wa_binding_message", "provider_message_id"),
        Index("ix_wa_binding_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Empty is reserved for legacy rows whose provider account was not recorded.
    provider_phone_number_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_attempt_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class WhatsAppProviderReceiptModel(Base):
    __tablename__ = "whatsapp_provider_receipts"
    __table_args__ = (
        CheckConstraint(
            "provider_status IN ('sent','delivered','read','failed')", name="ck_wa_receipt_status"
        ),
        CheckConstraint(
            "state IN ('pending','applied','superseded','source_missing','conflict','expired')",
            name="ck_wa_receipt_state",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_wa_receipt_attempts"),
        Index("ix_wa_receipt_due", "state", "next_attempt_at", "received_at"),
        Index("ix_wa_receipt_provider", "provider_phone_number_id", "provider_message_id"),
        Index("ix_wa_receipt_retention", "received_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    provider_phone_number_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_status_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    binding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_provider_message_bindings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processing_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
