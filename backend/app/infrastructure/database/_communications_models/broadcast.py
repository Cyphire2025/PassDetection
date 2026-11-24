"""WhatsApp broadcast mappings in the existing shared registry."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.model_base import JSONB, Base, _utcnow

if TYPE_CHECKING:
    from app.infrastructure.database.models import ClientGroupWhatsAppBroadcastLinkModel

    from .source import WhatsAppBroadcastRejectedContactModel


class WhatsAppBroadcastGroupModel(Base):
    __module__ = "app.infrastructure.database.communications_models"
    __tablename__ = "whatsapp_broadcast_groups"
    __table_args__ = (
        Index("ix_whatsapp_broadcast_groups_agency_created", "agency_id", "created_at"),
        Index(
            "ix_whatsapp_groups_agency_archive_created", "agency_id", "archived_at", "created_at"
        ),
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
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Canonical headings discovered across imported workbooks. Keeping the
    # bounded union on the list makes link configuration cheap even for large
    # recipient rosters and preserves headings whose column is currently empty.
    imported_field_keys: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
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
    __module__ = "app.infrastructure.database.communications_models"
    __tablename__ = "whatsapp_broadcast_recipients"
    __table_args__ = (
        Index("ix_whatsapp_recipient_source_seek", "broadcast_group_id", "id"),
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
    is_source_managed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merged_into_recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "whatsapp_broadcast_recipients.id",
            name="fk_whatsapp_recipient_merge_target",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    merged_contacts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
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
