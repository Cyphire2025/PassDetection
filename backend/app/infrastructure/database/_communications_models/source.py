"""WhatsApp source mappings in the existing shared registry."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.model_base import JSONB, Base, _utcnow

if TYPE_CHECKING:
    from .broadcast import WhatsAppBroadcastGroupModel


class WhatsAppBroadcastSourceContactModel(Base):
    """Every source traveller; several travellers may share one delivery recipient."""

    __module__ = "app.infrastructure.database.communications_models"
    __tablename__ = "whatsapp_broadcast_source_contacts"
    __table_args__ = (
        UniqueConstraint(
            "broadcast_group_id",
            "source_group_id",
            "source_submission_id",
            name="uq_whatsapp_source_contact_submission",
        ),
        Index("ix_whatsapp_source_contacts_agency_source", "agency_id", "source_group_id"),
        Index("ix_whatsapp_source_contacts_broadcast", "broadcast_group_id"),
        Index("ix_whatsapp_source_contacts_recipient", "recipient_id"),
        Index("ix_whatsapp_source_contacts_submission", "source_submission_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    broadcast_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False
    )
    source_submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_recipients.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    raw_phone_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    issue: Mapped[str | None] = mapped_column(String(32), nullable=True)
    imported_fields: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class WhatsAppTravellerPhoneOverrideModel(Base):
    """An exact traveller's broadcast-only correction, never collection authority."""

    __module__ = "app.infrastructure.database.communications_models"
    __tablename__ = "whatsapp_traveller_phone_overrides"
    __table_args__ = (
        UniqueConstraint(
            "broadcast_group_id", "passenger_id", name="uq_whatsapp_phone_override_passenger"
        ),
        Index("ix_whatsapp_phone_overrides_agency_group", "agency_id", "group_id"),
        Index("ix_whatsapp_phone_overrides_recipient", "recipient_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    broadcast_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_recipients.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_phone_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


class WhatsAppBroadcastRejectedContactModel(Base):
    __module__ = "app.infrastructure.database.communications_models"
    __tablename__ = "whatsapp_broadcast_rejected_contacts"
    __table_args__ = (
        Index("ix_whatsapp_rejected_source_seek", "broadcast_group_id", "id"),
        UniqueConstraint(
            "broadcast_group_id",
            "fingerprint",
            name="uq_whatsapp_rejected_contact_group_fingerprint",
        ),
        CheckConstraint(
            "row_number >= 1",
            name="ck_whatsapp_rejected_contact_row_number",
        ),
        CheckConstraint(
            "reason_code IN ('missing_phone', 'invalid_phone', 'missing_name', 'duplicate_phone')",
            name="ck_whatsapp_rejected_contact_reason_code",
        ),
        Index(
            "ix_whatsapp_rejected_contacts_group_created",
            "broadcast_group_id",
            "created_at",
        ),
        Index(
            "ix_whatsapp_rejected_contacts_group_display_order",
            "broadcast_group_id",
            "display_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    broadcast_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(31), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    raw_phone_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    imported_fields: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    display_order: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )

    broadcast_group: Mapped[WhatsAppBroadcastGroupModel] = relationship(
        "WhatsAppBroadcastGroupModel",
        back_populates="rejected_contacts",
    )


class WhatsAppBroadcastSupportContactModel(Base):
    __module__ = "app.infrastructure.database.communications_models"
    __tablename__ = "whatsapp_broadcast_support_contacts"
    __table_args__ = (
        UniqueConstraint(
            "broadcast_group_id",
            "normalized_phone_number",
            name="uq_whatsapp_support_group_phone",
        ),
        Index("ix_whatsapp_support_group_order", "broadcast_group_id", "sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broadcast_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
