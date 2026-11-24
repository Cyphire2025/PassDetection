"""Tenant-scoped linkage between upload groups and broadcast lists."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.model_base import JSONB, Base, _utcnow

if TYPE_CHECKING:
    from app.infrastructure.database._core_models.groups import ClientGroupModel
    from app.infrastructure.database.communications_models import WhatsAppBroadcastGroupModel


class ClientGroupWhatsAppBroadcastLinkModel(Base):
    """Tenant-scoped metadata link between an upload group and WhatsApp list."""
    __module__ = "app.infrastructure.database.models"

    __tablename__ = "client_group_whatsapp_broadcast_links"
    __table_args__ = (
        UniqueConstraint(
            "client_group_id",
            "broadcast_group_id",
            name="uq_client_group_whatsapp_broadcast_link",
        ),
        Index(
            "ix_client_group_whatsapp_links_agency_group",
            "agency_id",
            "client_group_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # NULL is the backwards-compatible legacy matcher. Explicit values are a
    # non-empty set of imported field keys evaluated with OR semantics.
    matching_field_keys: Mapped[list[str] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    sync_contacts_from_group: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    client_group: Mapped[ClientGroupModel] = relationship(
        "ClientGroupModel", back_populates="whatsapp_broadcast_links"
    )
    broadcast_group: Mapped[WhatsAppBroadcastGroupModel] = relationship(
        "WhatsAppBroadcastGroupModel", back_populates="client_group_links"
    )
