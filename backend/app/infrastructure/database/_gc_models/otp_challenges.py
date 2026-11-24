"""Hashed OTP challenge and verification records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.gc_mobile_models import _utcnow
from app.infrastructure.database.model_base import Base


class MobileOTPChallengeModel(Base):
    """Short-lived OTP state containing hashes only and neutral subject pointers."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "mobile_otp_challenges"
    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('passenger', 'client_manager', 'coordinator')",
            name="ck_mobile_otp_subject_type",
        ),
        CheckConstraint(
            "purpose IN ('login', 'activation', 'step_up')",
            name="ck_mobile_otp_purpose",
        ),
        CheckConstraint(
            "status IN ('pending', 'verified', 'consumed', 'expired', 'locked', 'cancelled')",
            name="ck_mobile_otp_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20 "
            "AND attempt_count <= max_attempts",
            name="ck_mobile_otp_attempts",
        ),
        CheckConstraint(
            "resend_count >= 0 AND max_resends BETWEEN 0 AND 20 AND resend_count <= max_resends",
            name="ck_mobile_otp_resends",
        ),
        CheckConstraint("expires_at > created_at", name="ck_mobile_otp_expiry"),
        CheckConstraint(
            "length(phone_lookup_hash) = 64 AND length(challenge_token_hash) = 64",
            name="ck_mobile_otp_lookup_hashes",
        ),
        CheckConstraint(
            "NOT (passenger_identity_id IS NOT NULL AND user_id IS NOT NULL)",
            name="ck_mobile_otp_single_subject",
        ),
        CheckConstraint(
            "(status IN ('verified', 'consumed') AND verified_at IS NOT NULL) OR "
            "(status NOT IN ('verified', 'consumed') AND verified_at IS NULL)",
            name="ck_mobile_otp_verified_shape",
        ),
        CheckConstraint(
            "(status = 'consumed' AND consumed_at IS NOT NULL) OR "
            "(status != 'consumed' AND consumed_at IS NULL)",
            name="ck_mobile_otp_consumed_shape",
        ),
        Index("ix_mobile_otp_phone_created", "phone_lookup_hash", "created_at"),
        Index("ix_mobile_otp_provider_reference", "provider_reference"),
        Index("ix_mobile_otp_expiry_status", "status", "expires_at"),
        Index(
            "uq_mobile_otp_pending_phone",
            "phone_lookup_hash",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True
    )
    passenger_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mobile_passenger_identities.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    subject_type: Mapped[str] = mapped_column(String(24), nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(16), nullable=False, default="login", server_default="login"
    )
    phone_lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    challenge_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    resend_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_resends: Mapped[int] = mapped_column(Integer, nullable=False)
    resend_available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
