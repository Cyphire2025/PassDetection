"""WhatsApp broadcast and delivery SQLAlchemy models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.model_base import JSONB, Base, _utcnow

if TYPE_CHECKING:
    from app.infrastructure.database.models import ClientGroupWhatsAppBroadcastLinkModel


class WhatsAppBroadcastGroupModel(Base):
    __tablename__ = "whatsapp_broadcast_groups"
    __table_args__ = (
        Index("ix_whatsapp_broadcast_groups_agency_created", "agency_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    organizing_company_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    recipient_opt_in_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    client_group_links: Mapped[list[ClientGroupWhatsAppBroadcastLinkModel]] = relationship(
        "ClientGroupWhatsAppBroadcastLinkModel",
        back_populates="broadcast_group",
        cascade="all, delete-orphan",
    )
    rejected_contacts: Mapped[list[WhatsAppBroadcastRejectedContactModel]] = relationship(
        "WhatsAppBroadcastRejectedContactModel",
        back_populates="broadcast_group",
        cascade="all, delete-orphan",
    )


class WhatsAppBroadcastRecipientModel(Base):
    __tablename__ = "whatsapp_broadcast_recipients"
    __table_args__ = (
        UniqueConstraint(
            "broadcast_group_id",
            "normalized_phone_number",
            name="uq_whatsapp_recipient_group_phone",
        ),
        Index("ix_whatsapp_recipients_group_created", "broadcast_group_id", "created_at"),
        Index(
            "ix_whatsapp_recipients_group_display_order",
            "broadcast_group_id",
            "display_order",
        ),
        Index(
            "ix_whatsapp_broadcast_recipients_roster_resolution",
            "suppressed_by_roster_resolution_id",
        ),
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
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone_number: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_phone_number: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    imported_fields: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    display_order: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suppressed_by_roster_resolution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "passport_roster_resolutions.id",
            name="fk_whatsapp_recipient_roster_resolution",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class WhatsAppBroadcastRejectedContactModel(Base):
    __tablename__ = "whatsapp_broadcast_rejected_contacts"
    __table_args__ = (
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


class WhatsAppMessageLogModel(Base):
    __tablename__ = "whatsapp_message_logs"
    __table_args__ = (
        Index("ix_whatsapp_message_logs_group_created", "broadcast_group_id", "created_at"),
        Index(
            "uq_whatsapp_active_explicit_resend",
            "recipient_id",
            "message_type",
            unique=True,
            postgresql_where=text(
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
    rendered_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    header_parameter_values: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    template_parameter_values: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
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
