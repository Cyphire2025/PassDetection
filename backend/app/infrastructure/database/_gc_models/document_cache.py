"""Derived personal-document metadata cached for authorized trip access."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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

from app.infrastructure.database.gc_mobile_models import _utcnow
from app.infrastructure.database.model_base import Base


class MobileDocumentMetadataCacheModel(Base):
    """Derived integrity metadata for an authoritative personal document.

    The object and ownership remain in the existing passport/distribution
    tables.  This projection stores only the bounded metadata needed to decide
    whether a device must download a new encrypted offline copy.
    """

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "mobile_document_metadata_cache"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "source_kind",
            "source_id",
            name="uq_mobile_document_cache_source",
        ),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_document_cache_access",
            ondelete="CASCADE",
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
            name="fk_mobile_document_cache_identity",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "source_kind IN ('passport_front', 'passport_back', 'distributed')",
            name="ck_mobile_document_cache_source_kind",
        ),
        CheckConstraint(
            "content_type IN ('application/pdf', 'image/jpeg', 'image/png', 'image/webp')",
            name="ck_mobile_document_cache_content_type",
        ),
        CheckConstraint(
            "byte_size > 0 AND byte_size <= 104857600",
            name="ck_mobile_document_cache_size",
        ),
        CheckConstraint(
            "length(storage_key_hash) = 64 AND length(checksum_sha256) = 64",
            name="ck_mobile_document_cache_hashes",
        ),
        CheckConstraint("version >= 1", name="ck_mobile_document_cache_version"),
        Index(
            "ix_mobile_document_cache_identity",
            "passenger_identity_id",
            "updated_at",
        ),
        Index(
            "ix_mobile_document_cache_access",
            "gc_group_access_id",
            "updated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passenger_identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passenger_submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    storage_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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
