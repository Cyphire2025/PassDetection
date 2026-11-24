"""Encrypted durable object-storage cleanup tombstones."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base, _utcnow


class StorageCleanupJobModel(Base):
    """Encrypted tombstone retained until object-storage deletion succeeds."""

    __module__ = "app.infrastructure.database.document_models"

    __tablename__ = "storage_cleanup_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'blocked')",
            name="ck_storage_cleanup_jobs_status",
        ),
        CheckConstraint("object_count > 0", name="ck_storage_cleanup_jobs_object_count"),
        CheckConstraint("attempts >= 0", name="ck_storage_cleanup_jobs_attempts"),
        CheckConstraint(
            "encryption_key_version >= 1",
            name="ck_storage_cleanup_jobs_key_version",
        ),
        Index(
            "ix_storage_cleanup_jobs_due",
            "status",
            "next_attempt_at",
            "created_at",
        ),
        Index(
            "ix_storage_cleanup_jobs_expired_lease",
            "status",
            "lease_expires_at",
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
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    context_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_keys_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_key_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    object_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
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
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )
