"""Revocable device sessions and their passenger identity bindings."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.gc_mobile_models import _utcnow
from app.infrastructure.database.model_base import Base


class MobileDeviceSessionModel(Base):
    """Revocable mobile session bound to one installation and token family."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "mobile_device_sessions"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", name="uq_mobile_session_agency"),
        UniqueConstraint(
            "id",
            "agency_id",
            "refresh_family_id",
            name="uq_mobile_session_refresh_family",
        ),
        ForeignKeyConstraint(
            ["passenger_identity_id", "agency_id"],
            ["mobile_passenger_identities.id", "mobile_passenger_identities.agency_id"],
            name="fk_mobile_session_passenger",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["selected_gc_group_access_id", "agency_id", "selected_group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_session_selected_group",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "subject_role IN ('passenger', 'client_manager', 'coordinator')",
            name="ck_mobile_session_subject_role",
        ),
        CheckConstraint(
            "platform IN ('android', 'ios')",
            name="ck_mobile_session_platform",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked', 'expired')",
            name="ck_mobile_session_status",
        ),
        CheckConstraint(
            "session_generation >= 0",
            name="ck_mobile_session_generation",
        ),
        CheckConstraint(
            "length(device_identifier_hash) = 64",
            name="ck_mobile_session_device_hash",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_mobile_session_expiry",
        ),
        CheckConstraint(
            "(subject_role = 'passenger' AND user_id IS NULL "
            "AND passenger_subject_hash IS NOT NULL) OR "
            "(subject_role IN ('client_manager', 'coordinator') "
            "AND user_id IS NOT NULL AND passenger_identity_id IS NULL "
            "AND passenger_subject_hash IS NULL)",
            name="ck_mobile_session_subject_shape",
        ),
        CheckConstraint(
            "passenger_identity_id IS NULL OR subject_role = 'passenger'",
            name="ck_mobile_session_passenger_role",
        ),
        CheckConstraint(
            "(selected_gc_group_access_id IS NULL) = (selected_group_id IS NULL)",
            name="ck_mobile_session_selected_group_pair",
        ),
        CheckConstraint(
            "(status = 'active' AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL) OR "
            "status = 'expired'",
            name="ck_mobile_session_state_shape",
        ),
        Index(
            "uq_mobile_session_user_device_active",
            "user_id",
            "device_identifier_hash",
            unique=True,
            postgresql_where=text("status = 'active' AND user_id IS NOT NULL"),
            sqlite_where=text("status = 'active' AND user_id IS NOT NULL"),
        ),
        Index(
            "uq_mobile_session_passenger_device_active",
            "passenger_subject_hash",
            "device_identifier_hash",
            unique=True,
            postgresql_where=text("status = 'active' AND passenger_subject_hash IS NOT NULL"),
            sqlite_where=text("status = 'active' AND passenger_subject_hash IS NOT NULL"),
        ),
        Index("ix_mobile_session_expiry", "status", "expires_at"),
        Index("ix_mobile_session_agency_seen", "agency_id", "last_seen_at"),
        Index("ix_mobile_session_account", "agency_id", "account_id"),
        Index(
            "ix_mobile_session_group_status_expiry",
            "agency_id",
            "selected_gc_group_access_id",
            "status",
            "expires_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    subject_role: Mapped[str] = mapped_column(String(24), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    # Stable client-side cache/account namespace. Passenger identity_id changes
    # when the same verified account switches trips; account_id deliberately
    # does not. For newly issued single-trip and staff sessions it equals the
    # initial principal id, preserving existing device cache namespaces.
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passenger_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    passenger_subject_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_gc_group_access_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    selected_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    device_identifier_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    app_version: Mapped[str] = mapped_column(String(32), nullable=False)
    device_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    session_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    refresh_family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    created_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set only after the device commits a complete, version-matched trip sync
    # and acknowledges it through /mobile/sync/ack.  Keeping this distinct
    # from last_seen_at prevents ordinary authentication/refresh traffic from
    # being reported as a successfully synchronized device.
    last_sync_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
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


class MobilePassengerSessionIdentityModel(Base):
    """An exact passenger identity proven for one revocable device session.

    A passenger access token still names exactly one selected identity.  These
    rows only retain the bounded set that the same OTP/secondary-factor proof
    authorized, allowing a later trip switch without repeating OTP while
    preserving tenant, group, and identity ownership at the database layer.
    """

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "mobile_passenger_session_identities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "agency_id"],
            ["mobile_device_sessions.id", "mobile_device_sessions.agency_id"],
            name="fk_mobile_passenger_session_identity_session",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            [
                "passenger_identity_id",
                "gc_group_access_id",
                "agency_id",
                "group_id",
            ],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
            ],
            name="fk_mobile_passenger_session_identity_scope",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "identity_claim_generation >= 0",
            name="ck_mobile_passenger_session_identity_generation",
        ),
        Index(
            "ix_mobile_passenger_session_identity_group",
            "session_id",
            "group_id",
        ),
        Index(
            "ix_mobile_passenger_session_identity_identity",
            "passenger_identity_id",
            "session_id",
        ),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    passenger_identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    identity_claim_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    authorized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
