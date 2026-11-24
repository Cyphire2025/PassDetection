"""WhatsApp welcome mappings in the existing shared registry."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class WhatsAppPhoneWelcomeModel(Base):
    """One welcome prerequisite per tenant and actual destination phone."""

    __module__ = "app.infrastructure.database.communications_models"
    __tablename__ = "whatsapp_phone_welcomes"
    __table_args__ = (
        UniqueConstraint("agency_id", "normalized_phone_number", name="uq_whatsapp_phone_welcome"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    normalized_phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # Logical source UUID, deliberately not a foreign key: removing an imported
    # list must not erase confirmed welcome delivery to this phone.
    attempt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempt_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_status_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class WhatsAppPhoneWelcomeAttemptModel(Base):
    """Frozen, durable traveller welcome intent outside the imported roster."""

    __module__ = "app.infrastructure.database.communications_models"
    __tablename__ = "whatsapp_phone_welcome_attempts"
    __table_args__ = (Index("ix_phone_welcome_attempt_batch_status", "batch_id", "status"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False
    )
    broadcast_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    passenger_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    normalized_phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    template_name: Mapped[str] = mapped_column(String(255), nullable=False)
    rendered_message: Mapped[str] = mapped_column(Text, nullable=False)
    header_parameter_values: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    template_parameter_values: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_status_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
