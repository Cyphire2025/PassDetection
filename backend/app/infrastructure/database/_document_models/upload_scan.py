"""Private malware decisions and encrypted quarantine locators."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base, _utcnow


class UntrustedUploadScanModel(Base):
    """Privacy-safe malware decision and optional private quarantine locator."""

    __module__ = "app.infrastructure.database.document_models"

    __tablename__ = "untrusted_upload_scans"
    __table_args__ = (
        CheckConstraint(
            "scan_status IN ('clean', 'infected', 'scanner_error', 'malformed', 'oversized')",
            name="ck_untrusted_upload_scan_status",
        ),
        CheckConstraint(
            "disposition IN ('accepted', 'rejected', 'quarantined')",
            name="ck_untrusted_upload_disposition",
        ),
        CheckConstraint(
            "length(content_sha256) = 64",
            name="ck_untrusted_upload_sha256",
        ),
        CheckConstraint(
            "byte_size >= 0",
            name="ck_untrusted_upload_byte_size",
        ),
        CheckConstraint(
            "(disposition = 'quarantined' AND quarantine_key_ciphertext IS NOT NULL "
            "AND quarantine_key_version IS NOT NULL) OR "
            "(disposition <> 'quarantined' AND quarantine_key_ciphertext IS NULL "
            "AND quarantine_key_version IS NULL)",
            name="ck_untrusted_upload_quarantine_shape",
        ),
        Index(
            "ix_untrusted_upload_scan_created",
            "agency_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_untrusted_upload_quarantine_retention",
            "disposition",
            "retention_expires_at",
            "id",
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
    ingestion_flow: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    declared_media_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scanner_name: Mapped[str] = mapped_column(String(64), nullable=False)
    scanner_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scan_status: Mapped[str] = mapped_column(String(24), nullable=False)
    disposition: Mapped[str] = mapped_column(String(16), nullable=False)
    detection_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    quarantine_key_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    quarantine_key_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
