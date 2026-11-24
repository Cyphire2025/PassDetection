"""Coordinator runtime identities and activity participation evidence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base, _utcnow


class AttendanceRuntimeRegistrationModel(Base):
    """Privacy-safe coordinator installation/runtime registration."""

    __tablename__ = "attendance_runtime_registrations"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "agency_id",
            "coordinator_user_id",
            name="uq_attendance_runtime_id_tenant_coordinator",
        ),
        UniqueConstraint(
            "agency_id",
            "coordinator_user_id",
            "runtime_identifier_hash",
            name="uq_attendance_runtime_identifier",
        ),
        ForeignKeyConstraint(
            ["coordinator_user_id", "agency_id"],
            ["users.id", "users.agency_id"],
            name="fk_attendance_runtime_coordinator_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "runtime_kind IN ('native_mobile', 'pwa', 'webview', 'legacy_account')",
            name="ck_attendance_runtime_kind",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked', 'expired', 'lost', 'replaced')",
            name="ck_attendance_runtime_status",
        ),
        CheckConstraint(
            "length(runtime_identifier_hash) = 64",
            name="ck_attendance_runtime_identifier_hash",
        ),
        CheckConstraint(
            "expires_at > registered_at",
            name="ck_attendance_runtime_expiry",
        ),
        CheckConstraint(
            "(status = 'active' AND revoked_at IS NULL) OR "
            "(status <> 'active' AND revoked_at IS NOT NULL)",
            name="ck_attendance_runtime_revocation_shape",
        ),
        Index(
            "ix_attendance_runtime_coordinator_status",
            "agency_id",
            "coordinator_user_id",
            "status",
            "expires_at",
        ),
        Index(
            "ix_attendance_runtime_native_session",
            "native_mobile_session_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    runtime_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    runtime_identifier_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    native_mobile_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mobile_device_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        server_default="active",
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    replaced_by_runtime_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_runtime_registrations.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )


class AttendanceSessionRuntimeParticipantModel(Base):
    """A runtime that produced evidence and must participate in closeout."""

    __tablename__ = "attendance_session_runtime_participants"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "runtime_registration_id",
            name="uq_attendance_session_runtime_participant",
        ),
        ForeignKeyConstraint(
            ["session_id", "agency_id"],
            ["attendance_sessions.id", "attendance_sessions.agency_id"],
            name="fk_attendance_participant_session_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["runtime_registration_id", "agency_id", "coordinator_user_id"],
            [
                "attendance_runtime_registrations.id",
                "attendance_runtime_registrations.agency_id",
                "attendance_runtime_registrations.coordinator_user_id",
            ],
            name="fk_attendance_participant_runtime_tenant_coordinator",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "participation_source IN ('scan', 'checkpoint', 'discard', 'legacy')",
            name="ck_attendance_participant_source",
        ),
        CheckConstraint(
            "last_participated_at >= first_participated_at",
            name="ck_attendance_participant_time_order",
        ),
        Index(
            "ix_attendance_participants_session_coordinator",
            "session_id",
            "coordinator_user_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    runtime_registration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    participation_source: Mapped[str] = mapped_column(String(16), nullable=False)
    first_participated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    last_participated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
