"""Encrypted push registrations and durable delivery attempts."""

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
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.gc_mobile_models import _utcnow
from app.infrastructure.database.model_base import Base


class MobilePushRegistrationModel(Base):
    """Application-encrypted APNs/FCM token bound to a revocable session."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "mobile_push_registrations"
    __table_args__ = (
        UniqueConstraint("provider", "token_lookup_hash", name="uq_mobile_push_provider_token"),
        ForeignKeyConstraint(
            ["session_id", "agency_id"],
            ["mobile_device_sessions.id", "mobile_device_sessions.agency_id"],
            name="fk_mobile_push_session",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "provider IN ('expo', 'fcm', 'apns')",
            name="ck_mobile_push_provider",
        ),
        CheckConstraint("platform IN ('android', 'ios')", name="ck_mobile_push_platform"),
        CheckConstraint(
            "apns_environment IS NULL OR apns_environment IN ('development', 'production')",
            name="ck_mobile_push_apns_environment",
        ),
        CheckConstraint(
            "environment IN ('development', 'production')",
            name="ck_mobile_push_environment",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled', 'revoked')",
            name="ck_mobile_push_status",
        ),
        CheckConstraint("token_key_version >= 1", name="ck_mobile_push_key_version"),
        CheckConstraint(
            "length(token_ciphertext) > 0 AND length(token_lookup_hash) = 64",
            name="ck_mobile_push_token_material",
        ),
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL) OR "
            "(status != 'revoked' AND revoked_at IS NULL)",
            name="ck_mobile_push_revoked_shape",
        ),
        Index("ix_mobile_push_session_status", "session_id", "status"),
        Index("ix_mobile_push_failure", "status", "last_failure_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    app_bundle_id: Mapped[str] = mapped_column(String(255), nullable=False)
    apns_environment: Mapped[str | None] = mapped_column(String(11), nullable=True)
    token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    token_lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    notifications_authorized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    last_registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class MobilePushDeliveryModel(Base):
    """Durable provider ticket and receipt state for one device delivery."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "mobile_push_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "notification_id",
            "registration_id",
            name="uq_mobile_push_delivery_target",
        ),
        CheckConstraint(
            "provider IN ('expo', 'fcm', 'apns')",
            name="ck_mobile_push_delivery_provider",
        ),
        CheckConstraint(
            "status IN ('submitting', 'retry', 'receipt_pending', 'delivered', "
            "'failed', 'cancelled', 'provider_accepted', 'unknown')",
            name="ck_mobile_push_delivery_status",
        ),
        CheckConstraint(
            "send_attempts >= 0 AND receipt_attempts >= 0",
            name="ck_mobile_push_delivery_attempts",
        ),
        CheckConstraint(
            "(provider_ticket_id IS NULL AND submitted_at IS NULL) OR "
            "(provider_ticket_id IS NOT NULL AND submitted_at IS NOT NULL)",
            name="ck_mobile_push_delivery_ticket_shape",
        ),
        CheckConstraint(
            "status NOT IN ('receipt_pending', 'delivered', 'provider_accepted') OR "
            "provider_ticket_id IS NOT NULL",
            name="ck_mobile_push_delivery_receipt_shape",
        ),
        CheckConstraint(
            "(status = 'delivered' AND delivered_at IS NOT NULL) OR "
            "(status != 'delivered' AND delivered_at IS NULL)",
            name="ck_mobile_push_delivery_delivered_shape",
        ),
        CheckConstraint(
            "(status = 'failed' AND failed_at IS NOT NULL) OR "
            "(status != 'failed' AND failed_at IS NULL)",
            name="ck_mobile_push_delivery_failed_shape",
        ),
        Index(
            "uq_mobile_push_delivery_provider_ticket",
            "provider",
            "provider_ticket_id",
            unique=True,
            postgresql_where=text("provider_ticket_id IS NOT NULL"),
            sqlite_where=text("provider_ticket_id IS NOT NULL"),
        ),
        Index(
            "ix_mobile_push_delivery_due",
            "provider",
            "status",
            "next_attempt_at",
        ),
        Index("ix_mobile_push_delivery_notification", "notification_id", "status"),
        Index("ix_mobile_push_delivery_registration", "registration_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mobile_notifications.id", ondelete="CASCADE"),
        nullable=False,
    )
    registration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mobile_push_registrations.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_ticket_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="submitting", server_default="submitting"
    )
    send_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    receipt_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
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
