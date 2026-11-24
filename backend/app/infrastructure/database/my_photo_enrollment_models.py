"""Passenger consent, reference lifecycle and durable deletion claims."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
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


class MyPhotoEnrollmentModel(Base):
    """Versioned passenger consent and provider-reference lifecycle."""

    __tablename__ = "my_photo_enrollments"

    __table_args__ = (
        UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_enrollment_scope"),
        UniqueConstraint(
            "id",
            "passenger_identity_id",
            "agency_id",
            "group_id",
            name="uq_my_photo_enrollment_passenger_scope",
        ),
        UniqueConstraint(
            "passenger_identity_id", "group_id", name="uq_my_photo_enrollment_passenger"
        ),
        ForeignKeyConstraint(
            [
                "passenger_identity_id",
                "gc_group_access_id",
                "agency_id",
                "group_id",
                "passenger_submission_id",
            ],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
                "mobile_passenger_identities.passenger_submission_id",
            ],
            name="fk_my_photo_enrollment_passenger",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('ready', 'session_pending', 'processing', 'enrolled', 'rejected', "
            "'cooldown', 'revoked', 'deleted')",
            name="ck_my_photo_enrollment_status",
        ),
        CheckConstraint(
            "length(trim(consent_version)) BETWEEN 1 AND 64",
            name="ck_my_photo_enrollment_consent",
        ),
        CheckConstraint(
            "reference_version >= 0 AND attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20",
            name="ck_my_photo_enrollment_attempts",
        ),
        CheckConstraint(
            "(status = 'cooldown' AND cooldown_until IS NOT NULL) OR status != 'cooldown'",
            name="ck_my_photo_enrollment_cooldown",
        ),
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL) OR "
            "(status = 'deleted' AND deleted_at IS NOT NULL) OR "
            "status NOT IN ('revoked', 'deleted')",
            name="ck_my_photo_enrollment_terminal",
        ),
        CheckConstraint(
            "(status = 'enrolled' AND provider_reference_handle IS NOT NULL "
            "AND reference_version >= 1 AND enrolled_at IS NOT NULL) OR status != 'enrolled'",
            name="ck_my_photo_enrollment_enrolled",
        ),
        CheckConstraint(
            "provider_deletion_status IN ('not_required', 'pending', 'complete', 'failed')",
            name="ck_my_photo_enrollment_provider_deletion_status",
        ),
        CheckConstraint(
            "(deletion_idempotency_key IS NULL AND deletion_scope IS NULL) OR "
            "(deletion_idempotency_key IS NOT NULL AND deletion_scope IN "
            "('enrollment_only', 'enrollment_and_search_data'))",
            name="ck_my_photo_enrollment_deletion_request",
        ),
        CheckConstraint(
            "(status = 'deleted' AND deletion_idempotency_key IS NOT NULL) OR status != 'deleted'",
            name="ck_my_photo_enrollment_deleted_request",
        ),
        CheckConstraint(
            "(provider_deletion_status = 'not_required' "
            "AND provider_deletion_requested_at IS NULL "
            "AND provider_deletion_completed_at IS NULL "
            "AND provider_deletion_error_code IS NULL) OR "
            "(provider_deletion_status = 'pending' "
            "AND provider_deletion_requested_at IS NOT NULL "
            "AND provider_deletion_completed_at IS NULL) OR "
            "(provider_deletion_status = 'complete' "
            "AND provider_deletion_requested_at IS NOT NULL "
            "AND provider_deletion_completed_at IS NOT NULL "
            "AND provider_deletion_error_code IS NULL "
            "AND provider_reference_handle IS NULL) OR "
            "(provider_deletion_status = 'failed' "
            "AND provider_deletion_requested_at IS NOT NULL "
            "AND provider_deletion_completed_at IS NULL "
            "AND provider_deletion_error_code IS NOT NULL)",
            name="ck_my_photo_enrollment_provider_deletion_shape",
        ),
        CheckConstraint(
            "superseded_reference_deletion_status IN "
            "('not_required', 'pending', 'complete', 'failed')",
            name="ck_my_photo_enrollment_superseded_deletion_status",
        ),
        CheckConstraint(
            "provider_deletion_attempt_count BETWEEN 0 AND 20",
            name="ck_my_photo_enrollment_deletion_attempts",
        ),
        CheckConstraint(
            "superseded_deletion_attempt_count BETWEEN 0 AND 20",
            name="ck_my_photo_enrollment_superseded_deletion_attempts",
        ),
        CheckConstraint(
            "(superseded_reference_deletion_status = 'not_required' "
            "AND superseded_provider_reference_handle IS NULL "
            "AND superseded_reference_deletion_requested_at IS NULL "
            "AND superseded_reference_deletion_completed_at IS NULL "
            "AND superseded_reference_deletion_error_code IS NULL) OR "
            "(superseded_reference_deletion_status = 'pending' "
            "AND superseded_provider_reference_handle IS NOT NULL "
            "AND superseded_reference_deletion_requested_at IS NOT NULL "
            "AND superseded_reference_deletion_completed_at IS NULL) OR "
            "(superseded_reference_deletion_status = 'complete' "
            "AND superseded_provider_reference_handle IS NULL "
            "AND superseded_reference_deletion_requested_at IS NOT NULL "
            "AND superseded_reference_deletion_completed_at IS NOT NULL "
            "AND superseded_reference_deletion_error_code IS NULL) OR "
            "(superseded_reference_deletion_status = 'failed' "
            "AND superseded_provider_reference_handle IS NOT NULL "
            "AND superseded_reference_deletion_requested_at IS NOT NULL "
            "AND superseded_reference_deletion_completed_at IS NULL "
            "AND superseded_reference_deletion_error_code IS NOT NULL)",
            name="ck_my_photo_enrollment_superseded_deletion_shape",
        ),
        Index("ix_my_photo_enrollment_group_status", "group_id", "status"),
        Index(
            "ix_my_photo_enrollment_deletion_retry",
            "provider_deletion_next_attempt_at",
            "provider_deletion_attempt_count",
        ),
        Index(
            "ix_my_photo_enrollment_superseded_deletion_retry",
            "superseded_deletion_next_attempt_at",
            "superseded_deletion_attempt_count",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    passenger_identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    passenger_submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    consent_version: Mapped[str] = mapped_column(String(64), nullable=False)

    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    consent_idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="ready", server_default="ready"
    )

    provider_name: Mapped[str | None] = mapped_column(String(32), nullable=True)

    provider_reference_handle: Mapped[str | None] = mapped_column(String(4096), nullable=True)

    reference_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )

    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    deletion_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    deletion_scope: Mapped[str | None] = mapped_column(String(40), nullable=True)

    provider_deletion_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="not_required", server_default="not_required"
    )

    provider_deletion_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    provider_deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    provider_deletion_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    superseded_provider_reference_handle: Mapped[str | None] = mapped_column(
        String(4096), nullable=True
    )

    superseded_reference_deletion_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="not_required", server_default="not_required"
    )

    superseded_reference_deletion_error_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    superseded_reference_deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    superseded_reference_deletion_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    provider_deletion_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    provider_deletion_next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    provider_deletion_last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    superseded_deletion_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    superseded_deletion_next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    superseded_deletion_last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
