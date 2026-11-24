"""Attestation keys bound to registered device installations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.gc_mobile_models import _utcnow
from app.infrastructure.database.model_base import Base


class MobileAppAttestKeyModel(Base):
    """One server-verified Apple App Attest key per account installation.

    The raw key identifier is never persisted. The verifier returns only the
    bounded public verification material required for future assertions; the
    Secure Enclave private key never leaves the device.
    """

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "mobile_app_attest_keys"
    __table_args__ = (
        CheckConstraint(
            "length(device_identifier_hash) = 64",
            name="ck_mobile_app_attest_device_hash",
        ),
        CheckConstraint(
            "length(key_identifier_hash) = 64",
            name="ck_mobile_app_attest_key_hash",
        ),
        CheckConstraint(
            "length(verification_material) BETWEEN 32 AND 4096",
            name="ck_mobile_app_attest_material_size",
        ),
        CheckConstraint(
            "assertion_counter >= 0",
            name="ck_mobile_app_attest_counter",
        ),
        CheckConstraint(
            "environment IN ('development', 'production')",
            name="ck_mobile_app_attest_environment",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_mobile_app_attest_status",
        ),
        CheckConstraint(
            "(status = 'active' AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL)",
            name="ck_mobile_app_attest_state_shape",
        ),
        Index(
            "uq_mobile_app_attest_account_device_active",
            "agency_id",
            "account_id",
            "device_identifier_hash",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "uq_mobile_app_attest_key_active",
            "key_identifier_hash",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "ix_mobile_app_attest_account_status",
            "agency_id",
            "account_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    device_identifier_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    key_identifier_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_material: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    assertion_counter: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        server_default="active",
    )
    attested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_asserted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
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
