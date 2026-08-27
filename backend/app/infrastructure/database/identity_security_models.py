"""Durable workforce credential, MFA, and session-fencing state.

Only hashes or application-encrypted values are persisted. Raw activation
tokens, recovery tokens, TOTP secrets, and recovery codes are returned at
most once to the authorized caller and must never be logged.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class UserSecurityStateModel(Base):
    """One authoritative credential/session state row per platform user."""

    __tablename__ = "user_security_states"
    __table_args__ = (
        CheckConstraint(
            "credential_state IN ('invited', 'active')",
            name="ck_user_security_credential_state",
        ),
        CheckConstraint("session_version >= 1", name="ck_user_security_session_version"),
        CheckConstraint(
            "(mfa_secret_ciphertext IS NULL AND mfa_enabled_at IS NULL "
            "AND mfa_last_counter IS NULL) OR "
            "(mfa_secret_ciphertext IS NOT NULL AND mfa_enabled_at IS NOT NULL)",
            name="ck_user_security_mfa_shape",
        ),
        Index("ix_user_security_mfa_required", "mfa_required", "mfa_enabled_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    credential_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    session_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    mfa_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    mfa_secret_ciphertext: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_last_counter: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
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


class IdentityActionTokenModel(Base):
    """Single-use activation or password-recovery token, stored as a hash."""

    __tablename__ = "identity_action_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('activation', 'password_recovery')",
            name="ck_identity_action_token_purpose",
        ),
        CheckConstraint("length(token_hash) = 64", name="ck_identity_action_token_hash"),
        CheckConstraint("expires_at > created_at", name="ck_identity_action_token_expiry"),
        Index("ix_identity_action_user_purpose", "user_id", "purpose", "created_at"),
        Index("ix_identity_action_expiry", "expires_at", "consumed_at", "invalidated_at"),
        Index(
            "uq_identity_action_active_user_purpose",
            "user_id",
            "purpose",
            unique=True,
            postgresql_where=text("consumed_at IS NULL AND invalidated_at IS NULL"),
            sqlite_where=text("consumed_at IS NULL AND invalidated_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    token_key_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="legacy-v1", server_default="legacy-v1"
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    request_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class IdentityNotificationOutboxModel(Base):
    """Encrypted, retryable identity notification staged with its action token."""

    __tablename__ = "identity_notification_outbox"
    __table_args__ = (
        UniqueConstraint(
            "dedupe_key",
            name="uq_identity_notification_outbox_dedupe",
        ),
        CheckConstraint(
            "purpose IN ('activation', 'password_recovery', 'admin_assisted_recovery')",
            name="ck_identity_notification_purpose",
        ),
        CheckConstraint(
            "channel IN ('email', 'sms')",
            name="ck_identity_notification_channel",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'delivered', 'dead_letter')",
            name="ck_identity_notification_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20 "
            "AND attempt_count <= max_attempts",
            name="ck_identity_notification_attempts",
        ),
        CheckConstraint(
            "length(dedupe_key) = 64",
            name="ck_identity_notification_dedupe_key",
        ),
        CheckConstraint(
            "length(encryption_key_id) BETWEEN 1 AND 64",
            name="ck_identity_notification_encryption_key_id",
        ),
        Index(
            "ix_identity_notification_due",
            "status",
            "next_attempt_at",
            "created_at",
        ),
        Index(
            "ix_identity_notification_expired_lease",
            "status",
            "lease_expires_at",
        ),
        Index(
            "ix_identity_notification_user_created",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action_token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identity_action_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    recipient_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        server_default="5",
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    provider_message_id_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class DashboardAuthChallengeModel(Base):
    """Short-lived, replay-safe second-factor or enrollment challenge."""

    __tablename__ = "dashboard_auth_challenges"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('mfa_login', 'mfa_enrollment')",
            name="ck_dashboard_auth_challenge_purpose",
        ),
        CheckConstraint(
            "status IN ('pending', 'consumed', 'expired', 'locked', 'cancelled')",
            name="ck_dashboard_auth_challenge_status",
        ),
        CheckConstraint("length(challenge_token_hash) = 64", name="ck_dashboard_auth_token_hash"),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20 "
            "AND attempt_count <= max_attempts",
            name="ck_dashboard_auth_attempts",
        ),
        CheckConstraint("expires_at > created_at", name="ck_dashboard_auth_expiry"),
        CheckConstraint(
            "(purpose = 'mfa_enrollment' AND pending_secret_ciphertext IS NOT NULL) OR "
            "(purpose = 'mfa_login' AND pending_secret_ciphertext IS NULL)",
            name="ck_dashboard_auth_pending_secret",
        ),
        Index("ix_dashboard_auth_user_created", "user_id", "created_at"),
        Index("ix_dashboard_auth_expiry_status", "expires_at", "status"),
        Index(
            "uq_dashboard_auth_pending_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    challenge_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    pending_secret_ciphertext: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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


class MFARecoveryCodeModel(Base):
    """One high-entropy MFA recovery code, persisted only as an HMAC."""

    __tablename__ = "mfa_recovery_codes"
    __table_args__ = (
        CheckConstraint("length(code_hash) = 64", name="ck_mfa_recovery_code_hash"),
        Index("ix_mfa_recovery_user_available", "user_id", "consumed_at"),
        Index("ix_mfa_recovery_consumed_created", "consumed_at", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


__all__ = [
    "DashboardAuthChallengeModel",
    "IdentityActionTokenModel",
    "IdentityNotificationOutboxModel",
    "MFARecoveryCodeModel",
    "UserSecurityStateModel",
]
