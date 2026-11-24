"""Discovered email artifacts, retrieval leases, and document classification."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.email_models import _utcnow
from app.infrastructure.database.model_base import Base


class EmailArtifactModel(Base):
    """One independently retryable attachment or controlled-link artifact."""
    __module__ = "app.infrastructure.database.email_models"

    __tablename__ = "email_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "provider_artifact_id",
            name="uq_email_artifacts_message_provider_artifact",
        ),
        UniqueConstraint("id", "agency_id", name="uq_email_artifacts_id_agency"),
        UniqueConstraint(
            "id",
            "agency_id",
            "owner_user_id",
            name="uq_email_artifacts_id_agency_owner",
        ),
        UniqueConstraint(
            "id",
            "message_id",
            "agency_id",
            name="uq_email_artifacts_id_message_agency",
        ),
        UniqueConstraint(
            "id",
            "message_id",
            "agency_id",
            "owner_user_id",
            name="uq_email_artifacts_id_message_agency_owner",
        ),
        ForeignKeyConstraint(
            ["message_id", "agency_id"],
            ["email_messages.id", "email_messages.agency_id"],
            name="fk_email_artifacts_message_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["message_id", "agency_id", "owner_user_id"],
            [
                "email_messages.id",
                "email_messages.agency_id",
                "email_messages.owner_user_id",
            ],
            name="fk_email_artifacts_message_agency_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["duplicate_of_id", "agency_id"],
            ["email_artifacts.id", "email_artifacts.agency_id"],
            name="fk_email_artifacts_duplicate_agency",
            ondelete="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["duplicate_of_id", "agency_id", "owner_user_id"],
            [
                "email_artifacts.id",
                "email_artifacts.agency_id",
                "email_artifacts.owner_user_id",
            ],
            name="fk_email_artifacts_duplicate_agency_owner",
            ondelete="NO ACTION",
        ),
        CheckConstraint(
            "kind IN ('attachment', 'inline', 'direct_link', 'cloud_link', 'portal_link')",
            name="ck_email_artifacts_source_kind",
        ),
        CheckConstraint(
            "retrieval_status IN ("
            "'pending', 'retrieving', 'retrieved', 'blocked', 'failed', 'ignored'"
            ")",
            name="ck_email_artifacts_retrieval_status",
        ),
        CheckConstraint(
            "processing_status IN ("
            "'pending', 'queued', 'processing', 'completed', 'review_required', "
            "'duplicate', 'failed', 'ignored'"
            ")",
            name="ck_email_artifacts_processing_status",
        ),
        CheckConstraint(
            "detected_type IN ('unknown', 'visa', 'flight_ticket', 'passport', 'other')",
            name="ck_email_artifacts_detected_type",
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_email_artifacts_size",
        ),
        CheckConstraint(
            "sha256_digest IS NULL OR length(sha256_digest) = 64",
            name="ck_email_artifacts_sha256",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1 AND attempt_count <= max_attempts",
            name="ck_email_artifacts_attempts",
        ),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name="ck_email_artifacts_lease_pair",
        ),
        CheckConstraint(
            "(source_url_ciphertext IS NULL) = (source_url_encryption_key_version IS NULL)",
            name="ck_email_artifacts_source_url_key_pair",
        ),
        CheckConstraint(
            "source_url_ciphertext IS NULL OR length(source_url_ciphertext) > 0",
            name="ck_email_artifacts_source_url_nonempty",
        ),
        CheckConstraint(
            "source_url_encryption_key_version IS NULL OR source_url_encryption_key_version >= 1",
            name="ck_email_artifacts_source_url_key_version",
        ),
        CheckConstraint(
            "duplicate_of_id IS NULL OR duplicate_of_id != id",
            name="ck_email_artifacts_not_self_duplicate",
        ),
        CheckConstraint(
            "match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 1)",
            name="ck_email_artifacts_match_confidence",
        ),
        Index(
            "ix_email_artifacts_agency_processing",
            "agency_id",
            "processing_status",
            "created_at",
        ),
        Index(
            "ix_email_artifacts_owner_processing",
            "owner_user_id",
            "processing_status",
            "created_at",
        ),
        Index(
            "ix_email_artifacts_retry_due",
            "retrieval_status",
            "next_retry_at",
            "lease_expires_at",
        ),
        Index(
            "ix_email_artifacts_agency_sha256",
            "agency_id",
            "sha256_digest",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider_artifact_id: Mapped[str] = mapped_column(String(768), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_attachment_id: Mapped[str | None] = mapped_column(String(768), nullable=True)
    provider_part_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    declared_content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verified_content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_url_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
        deferred=True,
    )
    source_url_encryption_key_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    retrieval_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    processing_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    detected_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    passenger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="SET NULL"),
        nullable=True,
    )
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
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
        default=3,
        server_default="3",
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
