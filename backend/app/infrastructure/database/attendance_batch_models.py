"""Durable bounded browser scan batches and idempotent item receipts."""

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
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base, _utcnow


class AttendanceScanBatchModel(Base):
    """Durable identity for one bounded browser attendance drain request."""

    __tablename__ = "attendance_scan_batches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "agency_id", "group_id"],
            [
                "attendance_sessions.id",
                "attendance_sessions.agency_id",
                "attendance_sessions.group_id",
            ],
            name="fk_attendance_scan_batch_session_tenant_group",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["runtime_registration_id", "agency_id", "coordinator_user_id"],
            [
                "attendance_runtime_registrations.id",
                "attendance_runtime_registrations.agency_id",
                "attendance_runtime_registrations.coordinator_user_id",
            ],
            name="fk_attendance_scan_batch_runtime_tenant_coordinator",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_attendance_scan_batch_fingerprint",
        ),
        CheckConstraint(
            "item_count BETWEEN 1 AND 50",
            name="ck_attendance_scan_batch_item_count",
        ),
        Index(
            "ix_attendance_scan_batches_session_created",
            "session_id",
            "created_at",
        ),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
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
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )


class AttendanceScanBatchResultModel(Base):
    """Privacy-minimized authoritative result for one idempotent batch item."""

    __tablename__ = "attendance_scan_batch_results"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "session_id",
            "client_event_id",
            name="uq_attendance_scan_batch_result_event",
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_attendance_scan_batch_result_fingerprint",
        ),
        CheckConstraint(
            "outcome IN ('counted', 'duplicate', 'rejected')",
            name="ck_attendance_scan_batch_result_outcome",
        ),
        CheckConstraint(
            "(outcome IN ('counted', 'duplicate') AND passenger_id IS NOT NULL "
            "AND error_code IS NULL AND retryable = false) OR "
            "(outcome = 'rejected' AND passenger_id IS NULL AND error_code IS NOT NULL)",
            name="ck_attendance_scan_batch_result_shape",
        ),
        Index(
            "ix_attendance_scan_batch_results_batch_order",
            "batch_id",
            "request_ordinal",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_scan_batches.batch_id", ondelete="CASCADE"),
        nullable=False,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="RESTRICT"),
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
    client_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    passenger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
