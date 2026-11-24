"""Count-only closeout checkpoints and privacy-safe discard evidence."""

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

from app.infrastructure.database.model_base import Base, _utcnow


class AttendanceDiscardTombstoneModel(Base):
    """Privacy-safe, idempotent evidence that a local scan was discarded."""

    __tablename__ = "attendance_discard_tombstones"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "coordinator_user_id",
            "discard_event_id",
            name="uq_attendance_discard_event",
        ),
        ForeignKeyConstraint(
            ["session_id", "agency_id", "group_id"],
            [
                "attendance_sessions.id",
                "attendance_sessions.agency_id",
                "attendance_sessions.group_id",
            ],
            name="fk_attendance_discard_session_tenant_group",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["runtime_registration_id", "agency_id", "coordinator_user_id"],
            [
                "attendance_runtime_registrations.id",
                "attendance_runtime_registrations.agency_id",
                "attendance_runtime_registrations.coordinator_user_id",
            ],
            name="fk_attendance_discard_runtime_tenant_coordinator",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "length(scan_reference) = 64",
            name="ck_attendance_discard_scan_reference",
        ),
        CheckConstraint(
            "reason_category IN ('operator_discard', 'coordinator_confirmed_rescan', "
            "'wrong_group', 'expired_authorization', 'activity_closed', 'duplicate', "
            "'duplicate_local_evidence', 'passenger_not_attending', 'privacy_or_data_error', "
            "'server_rejected', 'server_terminal_rejection', 'corrupted_entry', 'other')",
            name="ck_attendance_discard_reason",
        ),
        CheckConstraint(
            "status IN ('accepted', 'reconciled', 'overridden')",
            name="ck_attendance_discard_status",
        ),
        CheckConstraint(
            "received_at >= discarded_at AND retention_expires_at > received_at",
            name="ck_attendance_discard_time_order",
        ),
        Index(
            "ix_attendance_discard_session_received",
            "session_id",
            "received_at",
        ),
        Index(
            "ix_attendance_discard_retention",
            "retention_expires_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    runtime_registration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_runtime_registrations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    discard_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scan_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_category: Mapped[str] = mapped_column(String(32), nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="accepted",
        server_default="accepted",
    )
    retention_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciliation_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class AttendanceCloseoutCheckpointModel(Base):
    """Latest count-only closeout evidence for one coordinator and activity."""

    __tablename__ = "attendance_closeout_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "coordinator_user_id",
            "runtime_registration_id",
            name="uq_attendance_closeout_checkpoint_runtime",
        ),
        ForeignKeyConstraint(
            ["session_id", "agency_id"],
            ["attendance_sessions.id", "attendance_sessions.agency_id"],
            name="fk_attendance_closeout_session_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["runtime_registration_id", "agency_id", "coordinator_user_id"],
            [
                "attendance_runtime_registrations.id",
                "attendance_runtime_registrations.agency_id",
                "attendance_runtime_registrations.coordinator_user_id",
            ],
            name="fk_attendance_closeout_runtime_tenant_coordinator",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_attendance_closeout_legacy_account",
            "session_id",
            "coordinator_user_id",
            unique=True,
            postgresql_where=text("runtime_registration_id IS NULL"),
            sqlite_where=text("runtime_registration_id IS NULL"),
        ),
        CheckConstraint(
            "pending_count >= 0 AND sending_count >= 0 AND retryable_count >= 0 "
            "AND needs_review_count >= 0 AND unreviewed_rejected_count >= 0",
            name="ck_attendance_closeout_checkpoint_nonnegative_counts",
        ),
        CheckConstraint(
            "((pending_count + sending_count + retryable_count = 0 "
            "AND oldest_pending_age_seconds IS NULL) OR "
            "(pending_count + sending_count + retryable_count > 0 "
            "AND oldest_pending_age_seconds >= 0))",
            name="ck_attendance_closeout_checkpoint_oldest_pending",
        ),
        Index(
            "ix_attendance_closeout_checkpoints_session_reported",
            "session_id",
            "reported_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    runtime_registration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_runtime_registrations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retryable_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    needs_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unreviewed_rejected_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    oldest_pending_age_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )
