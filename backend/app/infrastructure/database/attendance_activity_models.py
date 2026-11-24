"""Canonical attendance activities and accepted scan evidence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
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

from app.infrastructure.database.model_base import Base, _utcnow


class AttendanceSessionModel(Base):
    __tablename__ = "attendance_sessions"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "agency_id",
            name="uq_attendance_sessions_id_agency",
        ),
        UniqueConstraint(
            "id",
            "agency_id",
            "group_id",
            name="uq_attendance_sessions_id_agency_group",
        ),
        CheckConstraint(
            "(scheduled_starts_at IS NULL AND scheduled_ends_at IS NULL) OR "
            "(scheduled_starts_at IS NOT NULL AND scheduled_ends_at IS NOT NULL "
            "AND scheduled_ends_at > scheduled_starts_at)",
            name="ck_attendance_sessions_scheduled_window",
        ),
        CheckConstraint(
            "schedule_version >= 1",
            name="ck_attendance_sessions_schedule_version",
        ),
        CheckConstraint(
            "schedule_timezone IS NULL OR "
            "(length(schedule_timezone) BETWEEN 1 AND 64 "
            "AND schedule_timezone = trim(schedule_timezone))",
            name="ck_attendance_sessions_schedule_timezone",
        ),
        Index("ix_attendance_sessions_group_status", "group_id", "status"),
        Index("ix_attendance_sessions_agency_created", "agency_id", "created_at"),
        Index(
            "ix_attendance_sessions_group_schedule",
            "group_id",
            "scheduled_starts_at",
            "scheduled_ends_at",
        ),
        Index(
            "uq_attendance_sessions_active_group_name",
            "group_id",
            "normalized_name",
            unique=True,
            postgresql_where=text("status IN ('draft', 'active') AND id = canonical_session_id"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(160), nullable=False)
    canonical_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "draft",
            "active",
            "completed",
            "cancelled",
            name="attendance_session_status_enum",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
        default="draft",
        index=True,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    scheduled_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    schedule_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schedule_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )


class AttendanceRecordModel(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "passenger_id", name="uq_attendance_records_session_passenger"
        ),
        UniqueConstraint(
            "session_id", "client_event_id", name="uq_attendance_records_session_client_event"
        ),
        ForeignKeyConstraint(
            ["runtime_registration_id", "agency_id", "coordinator_user_id"],
            [
                "attendance_runtime_registrations.id",
                "attendance_runtime_registrations.agency_id",
                "attendance_runtime_registrations.coordinator_user_id",
            ],
            name="fk_attendance_record_runtime_tenant_coordinator",
            ondelete="RESTRICT",
        ),
        Index("ix_attendance_records_agency_session", "agency_id", "session_id"),
        Index("ix_attendance_records_coordinator_scanned", "coordinator_user_id", "scanned_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    sync_source: Mapped[str] = mapped_column(
        Enum(
            "online",
            "offline",
            name="attendance_scan_source_enum",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
        default="online",
    )
    client_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    runtime_registration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_runtime_registrations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
