"""Recipient notification delivery and read state."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.gc_mobile_models import _utcnow
from app.infrastructure.database.model_base import JSONB, Base


class MobileNotificationModel(Base):
    """Per-recipient notification and read state with lock-screen-safe content."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "mobile_notifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_notification_access",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "recipient_type IN ('passenger', 'client_manager', 'coordinator', 'authored')",
            name="ck_mobile_notification_recipient_type",
        ),
        CheckConstraint(
            "(recipient_type = 'passenger' AND recipient_passenger_identity_id IS NOT NULL "
            "AND recipient_user_id IS NULL AND authored_recipient_id IS NULL) OR "
            "(recipient_type IN ('client_manager', 'coordinator') "
            "AND recipient_user_id IS NOT NULL "
            "AND recipient_passenger_identity_id IS NULL AND authored_recipient_id IS NULL) OR "
            "(recipient_type = 'authored' AND authored_recipient_id IS NOT NULL "
            "AND recipient_user_id IS NULL AND recipient_passenger_identity_id IS NULL "
            "AND group_id IS NULL AND gc_group_access_id IS NULL)",
            name="ck_mobile_notification_recipient_shape",
        ),
        CheckConstraint(
            "(notification_type = 'gc_alert') = (authored_recipient_id IS NOT NULL)",
            name="ck_mobile_notification_authored_type",
        ),
        ForeignKeyConstraint(
            ["authored_recipient_id", "agency_id"],
            ["gc_notification_recipients.id", "gc_notification_recipients.agency_id"],
            name="fk_mobile_notification_authored_recipient",
            ondelete="CASCADE",
        ),
        UniqueConstraint("authored_recipient_id", name="uq_mobile_notification_authored_recipient"),
        CheckConstraint(
            "category IN ('announcement', 'itinerary', 'room', 'flight', 'document', "
            "'coordinator', 'emergency', 'security', 'sync')",
            name="ck_mobile_notification_category",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'emergency')",
            name="ck_mobile_notification_priority",
        ),
        CheckConstraint(
            "status IN ('queued', 'sent', 'failed', 'cancelled')",
            name="ck_mobile_notification_status",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > available_at",
            name="ck_mobile_notification_expiry",
        ),
        CheckConstraint(
            "(gc_group_access_id IS NULL) = (group_id IS NULL)",
            name="ck_mobile_notification_group_pair",
        ),
        CheckConstraint(
            "NOT contains_sensitive_content OR lock_screen_body IS NULL",
            name="ck_mobile_notification_lock_screen_privacy",
        ),
        Index(
            "uq_mobile_notification_user_dedupe",
            "recipient_user_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("recipient_user_id IS NOT NULL"),
            sqlite_where=text("recipient_user_id IS NOT NULL"),
        ),
        Index(
            "uq_mobile_notification_passenger_dedupe",
            "recipient_passenger_identity_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("recipient_passenger_identity_id IS NOT NULL"),
            sqlite_where=text("recipient_passenger_identity_id IS NOT NULL"),
        ),
        Index(
            "ix_mobile_notification_user_feed",
            "recipient_user_id",
            "read_at",
            "created_at",
        ),
        Index(
            "ix_mobile_notification_passenger_feed",
            "recipient_passenger_identity_id",
            "read_at",
            "created_at",
        ),
        Index("ix_mobile_notification_delivery", "status", "available_at"),
        Index("ix_mobile_notification_push_due", "status", "next_push_attempt_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    gc_group_access_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    recipient_type: Mapped[str] = mapped_column(String(24), nullable=False)
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    recipient_passenger_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mobile_passenger_identities.id", ondelete="CASCADE"),
        nullable=True,
    )
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    authored_recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", server_default="normal"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    lock_screen_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lock_screen_body: Mapped[str | None] = mapped_column(String(240), nullable=True)
    contains_sensitive_content: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    deep_link_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    public_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_push_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
