"""Idempotent liveness sessions and expiring provider-operation claims."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base, _utcnow


class MyPhotoLivenessSessionModel(Base):
    """Single-use, short-lived liveness session without camera content."""

    __tablename__ = "my_photo_liveness_sessions"

    __table_args__ = (
        UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_liveness_scope"),
        UniqueConstraint(
            "enrollment_id", "idempotency_key", name="uq_my_photo_liveness_idempotency"
        ),
        ForeignKeyConstraint(
            ["enrollment_id", "agency_id", "group_id"],
            [
                "my_photo_enrollments.id",
                "my_photo_enrollments.agency_id",
                "my_photo_enrollments.group_id",
            ],
            name="fk_my_photo_liveness_enrollment",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "challenge_mode IN ('movement_and_light', 'movement_only')",
            name="ck_my_photo_liveness_mode",
        ),
        CheckConstraint(
            "status IN ('creating', 'created', 'running', 'completed', 'cancelled', 'expired', "
            "'rejected', 'failed')",
            name="ck_my_photo_liveness_status",
        ),
        CheckConstraint("expires_at > created_at", name="ck_my_photo_liveness_expiry"),
        CheckConstraint(
            "(provider_session_reference IS NULL AND status IN ('creating', 'failed')) OR "
            "(provider_session_reference IS NOT NULL AND status != 'creating')",
            name="ck_my_photo_liveness_provider_reference",
        ),
        CheckConstraint(
            "native_launch_handle IS NULL OR status IN ('created', 'running')",
            name="ck_my_photo_liveness_native_launch_handle",
        ),
        CheckConstraint(
            "(completion_idempotency_key IS NULL AND completion_outcome IS NULL) OR "
            "(completion_idempotency_key IS NOT NULL AND completion_outcome IN "
            "('completed', 'cancelled', 'expired', 'failed'))",
            name="ck_my_photo_liveness_completion",
        ),
        CheckConstraint(
            "(provider_claim_token IS NULL) = (provider_claim_expires_at IS NULL)",
            name="ck_my_photo_liveness_provider_claim_shape",
        ),
        CheckConstraint(
            "provider_claim_token IS NULL OR status IN ('creating', 'running')",
            name="ck_my_photo_liveness_provider_claim_status",
        ),
        CheckConstraint(
            "(consumed_at IS NULL AND status IN ('creating', 'created', 'running')) OR "
            "(consumed_at IS NOT NULL AND status IN "
            "('completed', 'cancelled', 'expired', 'rejected', 'failed'))",
            name="ck_my_photo_liveness_single_use",
        ),
        CheckConstraint(
            "(status IN ('creating', 'created', 'running') AND result_retryable IS NULL) OR "
            "(status IN ('completed', 'cancelled', 'expired', 'rejected', 'failed') "
            "AND result_retryable IS NOT NULL)",
            name="ck_my_photo_liveness_retryable_shape",
        ),
        Index("ix_my_photo_liveness_expiry", "status", "expires_at"),
        Index("ix_my_photo_liveness_provider_claim", "status", "provider_claim_expires_at"),
        Index(
            "uq_my_photo_liveness_active_enrollment",
            "enrollment_id",
            unique=True,
            postgresql_where=text("status IN ('creating', 'created', 'running')"),
            sqlite_where=text("status IN ('creating', 'created', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    enrollment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)

    challenge_mode: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="created", server_default="created"
    )

    provider_name: Mapped[str] = mapped_column(String(32), nullable=False)

    provider_session_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)

    native_launch_handle: Mapped[str | None] = mapped_column(String(512), nullable=True)

    stable_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    completion_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    completion_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)

    result_retryable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    provider_claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True)

    provider_claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
