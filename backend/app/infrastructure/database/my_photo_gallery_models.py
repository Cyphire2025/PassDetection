"""Gallery versions and bounded immutable upload manifests."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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


class MyPhotoGalleryModel(Base):
    """One deny-by-default gallery and published index for a trip."""

    __tablename__ = "my_photo_galleries"

    __table_args__ = (
        UniqueConstraint("group_id", name="uq_my_photo_gallery_group"),
        UniqueConstraint(
            "gc_group_access_id", "agency_id", "group_id", name="uq_my_photo_gallery_access"
        ),
        UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_gallery_scope"),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_my_photo_gallery_access",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('not_uploaded', 'awaiting_upload', 'processing', 'indexing', "
            "'ready', 'failed', 'removed')",
            name="ck_my_photo_gallery_status",
        ),
        CheckConstraint(
            "media_version >= 0 AND face_index_version >= 0 AND published_revision >= 0",
            name="ck_my_photo_gallery_versions",
        ),
        CheckConstraint(
            "total_asset_count >= 0 AND indexed_asset_count >= 0 AND failed_asset_count >= 0 "
            "AND indexed_asset_count + failed_asset_count <= total_asset_count",
            name="ck_my_photo_gallery_counts",
        ),
        CheckConstraint(
            "availability_ends_at IS NULL OR availability_starts_at IS NULL "
            "OR availability_ends_at > availability_starts_at",
            name="ck_my_photo_gallery_window",
        ),
        CheckConstraint(
            "retention_days IS NULL OR retention_days BETWEEN 1 AND 3650",
            name="ck_my_photo_gallery_retention",
        ),
        CheckConstraint(
            "(status = 'ready' AND published_revision >= 1 AND published_at IS NOT NULL "
            "AND provider_collection_reference IS NOT NULL) OR status != 'ready'",
            name="ck_my_photo_gallery_ready_shape",
        ),
        Index("ix_my_photo_gallery_availability", "feature_enabled", "status", "group_id"),
        Index("ix_my_photo_gallery_revision", "group_id", "published_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False
    )

    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    feature_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="not_uploaded", server_default="not_uploaded"
    )

    media_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    face_index_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    published_revision: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    total_asset_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    indexed_asset_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    failed_asset_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    all_group_photos_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    provider_collection_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)

    provider_name: Mapped[str | None] = mapped_column(String(32), nullable=True)

    index_model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    match_config_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default="unconfigured", server_default="unconfigured"
    )

    retention_policy_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default="v1", server_default="v1"
    )

    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    availability_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    availability_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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


class MyPhotoGalleryManifestModel(Base):
    """One bounded, multi-batch gallery revision awaiting atomic finalization."""

    __tablename__ = "my_photo_gallery_manifests"

    __table_args__ = (
        UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_manifest_scope"),
        UniqueConstraint("gallery_id", "manifest_identity", name="uq_my_photo_manifest_identity"),
        ForeignKeyConstraint(
            ["gallery_id", "agency_id", "group_id"],
            [
                "my_photo_galleries.id",
                "my_photo_galleries.agency_id",
                "my_photo_galleries.group_id",
            ],
            name="fk_my_photo_manifest_gallery",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('receiving', 'finalized', 'indexing', 'failed', 'cancelled')",
            name="ck_my_photo_manifest_status",
        ),
        CheckConstraint(
            "target_revision >= 1 AND total_asset_count BETWEEN 1 AND 5000 "
            "AND batch_count BETWEEN 1 AND 50 AND received_asset_count >= 0 "
            "AND received_asset_count <= total_asset_count",
            name="ck_my_photo_manifest_counts",
        ),
        CheckConstraint(
            "length(header_fingerprint) = 64 AND header_fingerprint = lower(header_fingerprint) "
            "AND (content_fingerprint IS NULL OR "
            "(length(content_fingerprint) = 64 "
            "AND content_fingerprint = lower(content_fingerprint)))",
            name="ck_my_photo_manifest_fingerprints",
        ),
        CheckConstraint(
            "retention_days BETWEEN 1 AND 3650 AND availability_ends_at > availability_starts_at",
            name="ck_my_photo_manifest_policy",
        ),
        Index("ix_my_photo_manifest_status", "status", "created_at"),
        Index(
            "uq_my_photo_manifest_active_revision",
            "gallery_id",
            "target_revision",
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
            sqlite_where=text("status <> 'cancelled'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    gallery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    manifest_identity: Mapped[str] = mapped_column(String(128), nullable=False)

    target_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)

    header_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    content_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    total_asset_count: Mapped[int] = mapped_column(Integer, nullable=False)

    batch_count: Mapped[int] = mapped_column(Integer, nullable=False)

    received_asset_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="receiving", server_default="receiving"
    )

    all_group_photos_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    retention_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)

    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)

    availability_starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    availability_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    provider_collection_reference: Mapped[str] = mapped_column(String(512), nullable=False)

    provider_model_version: Mapped[str] = mapped_column(String(64), nullable=False)

    match_config_version: Mapped[str] = mapped_column(String(64), nullable=False)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
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


class MyPhotoGalleryManifestBatchModel(Base):
    """Idempotency and completeness evidence for one <=100-object manifest batch."""

    __tablename__ = "my_photo_gallery_manifest_batches"

    __table_args__ = (
        UniqueConstraint("manifest_id", "batch_index", name="uq_my_photo_manifest_batch"),
        ForeignKeyConstraint(
            ["manifest_id", "agency_id", "group_id"],
            [
                "my_photo_gallery_manifests.id",
                "my_photo_gallery_manifests.agency_id",
                "my_photo_gallery_manifests.group_id",
            ],
            name="fk_my_photo_manifest_batch_manifest",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "batch_index BETWEEN 0 AND 49 AND asset_count BETWEEN 1 AND 100",
            name="ck_my_photo_manifest_batch_bounds",
        ),
        CheckConstraint(
            "length(batch_fingerprint) = 64 AND batch_fingerprint = lower(batch_fingerprint)",
            name="ck_my_photo_manifest_batch_fingerprint",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    manifest_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)

    batch_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    asset_count: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
