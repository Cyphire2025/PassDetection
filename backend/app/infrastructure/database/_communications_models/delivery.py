"""WhatsApp delivery mappings in the existing shared registry."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class WhatsAppMessageLogModel(Base):
    __module__ = "app.infrastructure.database.communications_models"
    __tablename__ = "whatsapp_message_logs"
    __table_args__ = (
        Index("ix_whatsapp_message_logs_group_created", "broadcast_group_id", "created_at"),
        Index("ix_whatsapp_message_logs_provider_id", "provider_message_id"),
        Index(
            "uq_whatsapp_active_explicit_resend",
            "recipient_id",
            "message_type",
            unique=True,
            postgresql_where=text(
                "is_explicit_resend = true "
                "AND status IN ('queued', 'processing', 'delivery_unknown')"
            ),
            sqlite_where=text(
                "is_explicit_resend = true "
                "AND status IN ('queued', 'processing', 'delivery_unknown')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    broadcast_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_recipients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Immutable destination: receipts must never qualify an edited roster phone.
    normalized_phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    provider_status_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    template_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rendered_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    header_parameter_values: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    template_parameter_values: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # Frozen scope for text-only document updates; never changes document send status.
    document_update_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_explicit_resend: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class WhatsAppRecipientMessageStateModel(Base):
    """Atomic per-recipient/per-message-type delivery claim and checklist."""

    __module__ = "app.infrastructure.database.communications_models"
    __tablename__ = "whatsapp_recipient_message_states"
    __table_args__ = (
        UniqueConstraint(
            "recipient_id",
            "message_type",
            name="uq_whatsapp_recipient_message_state",
        ),
        Index(
            "ix_whatsapp_message_states_group_type_status",
            "broadcast_group_id",
            "message_type",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broadcast_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_recipients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    provider_status_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )
