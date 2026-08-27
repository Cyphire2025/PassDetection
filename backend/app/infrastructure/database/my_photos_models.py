"""Tenant- and trip-scoped persistence for passenger My Photos.

Only metadata, opaque provider references, and durable state live here. Image
bytes, liveness video, face embeddings, provider payloads, public URLs, and
client-local paths are deliberately outside this schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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

from app.application.my_photos.limits import MAX_MY_PHOTOS_MEDIA_BYTES
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


class MyPhotoMediaAssetModel(Base):
    """Immutable metadata for one physical group photograph."""

    __tablename__ = "my_photo_media_assets"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_asset_scope"),
        UniqueConstraint("gallery_id", "immutable_asset_key", name="uq_my_photo_asset_gallery_key"),
        ForeignKeyConstraint(
            ["gallery_id", "agency_id", "group_id"],
            [
                "my_photo_galleries.id",
                "my_photo_galleries.agency_id",
                "my_photo_galleries.group_id",
            ],
            name="fk_my_photo_asset_gallery",
            ondelete="CASCADE",
        ),
        CheckConstraint("media_type = 'photo'", name="ck_my_photo_asset_media_type"),
        CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png', 'image/webp', 'image/heic')",
            name="ck_my_photo_asset_mime",
        ),
        CheckConstraint(
            "width BETWEEN 1 AND 100000 AND height BETWEEN 1 AND 100000 "
            "AND aspect_ratio > 0 AND aspect_ratio <= 100",
            name="ck_my_photo_asset_dimensions",
        ),
        CheckConstraint(
            f"byte_size BETWEEN 1 AND {MAX_MY_PHOTOS_MEDIA_BYTES}",
            name="ck_my_photo_asset_size",
        ),
        CheckConstraint(
            "length(checksum_sha256) = 64 AND checksum_sha256 = lower(checksum_sha256)",
            name="ck_my_photo_asset_checksum",
        ),
        CheckConstraint("orientation BETWEEN 1 AND 8", name="ck_my_photo_asset_orientation"),
        CheckConstraint(
            "published_revision >= 1 AND sort_rank >= 0",
            name="ck_my_photo_asset_revision_rank",
        ),
        CheckConstraint(
            "processing_state IN ('registered', 'awaiting_upload', 'processing', 'indexed', "
            "'failed', 'removed')",
            name="ck_my_photo_asset_processing",
        ),
        CheckConstraint(
            "availability_state IN ('registered', 'awaiting_upload', 'processing', 'indexed', "
            "'preview_available', 'original_available_online', 'archived_offline', "
            "'rehydration_requested', 'preparing_delivery', 'delivery_available', 'expired', "
            "'failed', 'removed')",
            name="ck_my_photo_asset_availability",
        ),
        CheckConstraint(
            "length(trim(original_filename)) BETWEEN 1 AND 255 "
            "AND original_filename NOT LIKE '%/%' AND original_filename NOT LIKE '%\\%'",
            name="ck_my_photo_asset_filename",
        ),
        CheckConstraint(
            "(archive_reference IS NULL OR archive_reference NOT LIKE '%://%') AND "
            "(storage_reference IS NULL OR storage_reference NOT LIKE '%://%')",
            name="ck_my_photo_asset_refs",
        ),
        Index(
            "ix_my_photo_asset_gallery_page",
            "gallery_id",
            "published_revision",
            "sort_rank",
            "id",
        ),
        Index(
            "ix_my_photo_asset_availability",
            "gallery_id",
            "availability_state",
            "id",
        ),
        Index("ix_my_photo_asset_checksum", "gallery_id", "checksum_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gallery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    immutable_asset_key: Mapped[str] = mapped_column(String(128), nullable=False)
    media_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="photo", server_default="photo"
    )
    archive_reference: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    storage_reference: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    aspect_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    orientation: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    processing_state: Mapped[str] = mapped_column(
        String(24), nullable=False, default="registered", server_default="registered"
    )
    availability_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="registered", server_default="registered"
    )
    published_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sort_rank: Mapped[int] = mapped_column(BigInteger, nullable=False)
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


class MyPhotoAssetVariantModel(Base):
    """Metadata for a thumbnail, preview, analysis, or delivery variant."""

    __tablename__ = "my_photo_asset_variants"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_variant_scope"),
        UniqueConstraint(
            "media_asset_id", "variant_kind", "delivery_version", name="uq_my_photo_variant_version"
        ),
        ForeignKeyConstraint(
            ["media_asset_id", "agency_id", "group_id"],
            [
                "my_photo_media_assets.id",
                "my_photo_media_assets.agency_id",
                "my_photo_media_assets.group_id",
            ],
            name="fk_my_photo_variant_asset",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "variant_kind IN ('thumbnail', 'preview', 'analysis', 'original', 'optimized')",
            name="ck_my_photo_variant_kind",
        ),
        CheckConstraint(
            "availability_state IN ('registered', 'awaiting_upload', 'processing', 'indexed', "
            "'preview_available', 'original_available_online', 'archived_offline', "
            "'rehydration_requested', 'preparing_delivery', 'delivery_available', 'expired', "
            "'failed', 'removed')",
            name="ck_my_photo_variant_availability",
        ),
        CheckConstraint(
            "width BETWEEN 1 AND 100000 AND height BETWEEN 1 AND 100000 "
            f"AND byte_size BETWEEN 1 AND {MAX_MY_PHOTOS_MEDIA_BYTES}",
            name="ck_my_photo_variant_dimensions",
        ),
        CheckConstraint(
            "length(checksum_sha256) = 64 AND checksum_sha256 = lower(checksum_sha256)",
            name="ck_my_photo_variant_checksum",
        ),
        CheckConstraint(
            "storage_reference IS NULL OR storage_reference NOT LIKE '%://%'",
            name="ck_my_photo_variant_ref",
        ),
        CheckConstraint("delivery_version >= 1", name="ck_my_photo_variant_version"),
        Index(
            "ix_my_photo_variant_delivery",
            "media_asset_id",
            "variant_kind",
            "availability_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    media_asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    variant_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_reference: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    availability_state: Mapped[str] = mapped_column(String(32), nullable=False)
    delivery_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1"
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class MyPhotoFaceOccurrenceModel(Base):
    """One indexed face occurrence mapped to one immutable media asset."""

    __tablename__ = "my_photo_face_occurrences"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_face_scope"),
        UniqueConstraint(
            "id",
            "media_asset_id",
            "agency_id",
            "group_id",
            name="uq_my_photo_face_asset_scope",
        ),
        UniqueConstraint(
            "agency_id",
            "group_id",
            "provider_name",
            "index_version",
            "provider_face_reference",
            name="uq_my_photo_face_provider",
        ),
        UniqueConstraint(
            "media_asset_id", "idempotency_identity", name="uq_my_photo_face_idempotency"
        ),
        ForeignKeyConstraint(
            ["media_asset_id", "agency_id", "group_id"],
            [
                "my_photo_media_assets.id",
                "my_photo_media_assets.agency_id",
                "my_photo_media_assets.group_id",
            ],
            name="fk_my_photo_face_asset",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "bounding_left BETWEEN 0 AND 1 AND bounding_top BETWEEN 0 AND 1 "
            "AND bounding_width > 0 AND bounding_width <= 1 "
            "AND bounding_height > 0 AND bounding_height <= 1 "
            "AND bounding_left + bounding_width <= 1.000001 "
            "AND bounding_top + bounding_height <= 1.000001",
            name="ck_my_photo_face_bounds",
        ),
        CheckConstraint(
            "quality_score IS NULL OR quality_score BETWEEN 0 AND 100",
            name="ck_my_photo_face_quality",
        ),
        CheckConstraint("index_version >= 1", name="ck_my_photo_face_index_version"),
        CheckConstraint(
            "(active = true AND deleted_at IS NULL) OR (active = false)",
            name="ck_my_photo_face_active",
        ),
        Index("ix_my_photo_face_asset_active", "media_asset_id", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    media_asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_face_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    idempotency_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    bounding_left: Mapped[float] = mapped_column(Float, nullable=False)
    bounding_top: Mapped[float] = mapped_column(Float, nullable=False)
    bounding_width: Mapped[float] = mapped_column(Float, nullable=False)
    bounding_height: Mapped[float] = mapped_column(Float, nullable=False)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    index_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


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


class MyPhotoSearchRunModel(Base):
    """Durable late-enrollment search against one published index version."""

    __tablename__ = "my_photo_search_runs"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "passenger_identity_id",
            "agency_id",
            "group_id",
            name="uq_my_photo_search_scope",
        ),
        UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_search_trip_scope"),
        UniqueConstraint(
            "passenger_identity_id",
            "group_id",
            "idempotency_key",
            name="uq_my_photo_search_idempotency",
        ),
        ForeignKeyConstraint(
            ["enrollment_id", "passenger_identity_id", "agency_id", "group_id"],
            [
                "my_photo_enrollments.id",
                "my_photo_enrollments.passenger_identity_id",
                "my_photo_enrollments.agency_id",
                "my_photo_enrollments.group_id",
            ],
            name="fk_my_photo_search_enrollment",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["gallery_id", "agency_id", "group_id"],
            [
                "my_photo_galleries.id",
                "my_photo_galleries.agency_id",
                "my_photo_galleries.group_id",
            ],
            name="fk_my_photo_search_gallery",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('queued', 'searching', 'complete', 'failed', 'cancelled')",
            name="ck_my_photo_search_status",
        ),
        CheckConstraint(
            "gallery_revision >= 1 AND face_index_version >= 1 AND enrollment_version >= 1",
            name="ck_my_photo_search_versions",
        ),
        CheckConstraint(
            "processed_face_count >= 0 AND total_face_count >= 0 "
            "AND processed_face_count <= total_face_count AND matched_asset_count >= 0 "
            "AND matched_asset_count <= total_face_count "
            "AND best_match_count >= 0 AND possible_match_count >= 0 "
            "AND best_match_count + possible_match_count = matched_asset_count",
            name="ck_my_photo_search_progress",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20",
            name="ck_my_photo_search_attempts",
        ),
        Index(
            "ix_my_photo_search_passenger_current",
            "passenger_identity_id",
            "group_id",
            "gallery_revision",
            "created_at",
        ),
        Index("ix_my_photo_search_lease", "status", "lease_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enrollment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passenger_identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gallery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gallery_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    face_index_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    enrollment_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    processed_face_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_face_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    matched_asset_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    best_match_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    possible_match_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    checkpoint_cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stable_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class MyPhotoMatchModel(Base):
    """Passenger-to-media association; physical media remains single-copy."""

    __tablename__ = "my_photo_matches"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_match_scope"),
        UniqueConstraint(
            "search_run_id",
            "passenger_identity_id",
            "media_asset_id",
            name="uq_my_photo_match_run_asset",
        ),
        ForeignKeyConstraint(
            ["search_run_id", "passenger_identity_id", "agency_id", "group_id"],
            [
                "my_photo_search_runs.id",
                "my_photo_search_runs.passenger_identity_id",
                "my_photo_search_runs.agency_id",
                "my_photo_search_runs.group_id",
            ],
            name="fk_my_photo_match_search",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["media_asset_id", "agency_id", "group_id"],
            [
                "my_photo_media_assets.id",
                "my_photo_media_assets.agency_id",
                "my_photo_media_assets.group_id",
            ],
            name="fk_my_photo_match_asset",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["face_occurrence_id", "media_asset_id", "agency_id", "group_id"],
            [
                "my_photo_face_occurrences.id",
                "my_photo_face_occurrences.media_asset_id",
                "my_photo_face_occurrences.agency_id",
                "my_photo_face_occurrences.group_id",
            ],
            name="fk_my_photo_match_face",
            ondelete="RESTRICT",
        ),
        CheckConstraint("similarity BETWEEN 0 AND 100", name="ck_my_photo_match_similarity"),
        CheckConstraint("display_tier IN ('best', 'possible')", name="ck_my_photo_match_tier"),
        CheckConstraint(
            "feedback IN ('none', 'this_is_me', 'not_me')",
            name="ck_my_photo_match_feedback",
        ),
        CheckConstraint(
            "(active = true AND superseded_at IS NULL) OR "
            "(active = false AND superseded_at IS NOT NULL)",
            name="ck_my_photo_match_active",
        ),
        Index(
            "uq_my_photo_match_active_asset",
            "passenger_identity_id",
            "media_asset_id",
            unique=True,
            postgresql_where=text("active = true"),
            sqlite_where=text("active = true"),
        ),
        Index(
            "ix_my_photo_match_page",
            "passenger_identity_id",
            "gallery_revision",
            "active",
            "display_tier",
            "sort_rank",
            "media_asset_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passenger_identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    media_asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    face_occurrence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gallery_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    display_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    match_config_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feedback: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none", server_default="none"
    )
    feedback_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_rank: Mapped[int] = mapped_column(BigInteger, nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class MyPhotoJobModel(Base):
    """Durable bounded job record for index/search/variant/media preparation."""

    __tablename__ = "my_photo_jobs"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_job_scope"),
        UniqueConstraint(
            "gallery_id", "job_type", "idempotency_key", name="uq_my_photo_job_idempotency"
        ),
        ForeignKeyConstraint(
            ["gallery_id", "agency_id", "group_id"],
            [
                "my_photo_galleries.id",
                "my_photo_galleries.agency_id",
                "my_photo_galleries.group_id",
            ],
            name="fk_my_photo_job_gallery",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["media_asset_id", "agency_id", "group_id"],
            [
                "my_photo_media_assets.id",
                "my_photo_media_assets.agency_id",
                "my_photo_media_assets.group_id",
            ],
            name="fk_my_photo_job_asset",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["search_run_id", "agency_id", "group_id"],
            [
                "my_photo_search_runs.id",
                "my_photo_search_runs.agency_id",
                "my_photo_search_runs.group_id",
            ],
            name="fk_my_photo_job_search",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "job_type IN ('index_gallery', 'generate_variants', 'search_passenger', "
            "'prepare_media', 'refresh_searches')",
            name="ck_my_photo_job_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'retrying', 'succeeded', 'cancelled', 'failed')",
            name="ck_my_photo_job_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20 "
            "AND processed_count >= 0 AND total_count >= 0 AND processed_count <= total_count "
            "AND succeeded_count >= 0 AND failed_count >= 0 "
            "AND succeeded_count + failed_count <= processed_count",
            name="ck_my_photo_job_counts",
        ),
        CheckConstraint(
            "request_fingerprint IS NULL OR "
            "(length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint))",
            name="ck_my_photo_job_request_fingerprint",
        ),
        CheckConstraint(
            "(job_type IN ('index_gallery', 'refresh_searches') "
            "AND media_asset_id IS NULL AND search_run_id IS NULL "
            "AND target_revision IS NOT NULL) OR "
            "(job_type IN ('generate_variants', 'prepare_media') "
            "AND media_asset_id IS NOT NULL AND search_run_id IS NULL "
            "AND target_revision IS NULL) OR "
            "(job_type = 'search_passenger' AND media_asset_id IS NULL "
            "AND search_run_id IS NOT NULL AND target_revision IS NULL)",
            name="ck_my_photo_job_target",
        ),
        CheckConstraint(
            "target_revision IS NULL OR target_revision >= 1",
            name="ck_my_photo_job_target_revision",
        ),
        Index("ix_my_photo_job_claim", "job_type", "status", "next_attempt_at", "created_at"),
        Index("ix_my_photo_job_lease", "status", "lease_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gallery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    media_asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    search_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    checkpoint_cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    processed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    succeeded_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stable_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class MyPhotoDeliveryAuthorizationModel(Base):
    """Short-lived delivery capability metadata; never a permanent URL."""

    __tablename__ = "my_photo_delivery_authorizations"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_delivery_scope"),
        UniqueConstraint(
            "passenger_identity_id",
            "media_asset_id",
            "quality",
            "idempotency_key",
            name="uq_my_photo_delivery_idempotency",
        ),
        ForeignKeyConstraint(
            ["media_asset_id", "agency_id", "group_id"],
            [
                "my_photo_media_assets.id",
                "my_photo_media_assets.agency_id",
                "my_photo_media_assets.group_id",
            ],
            name="fk_my_photo_delivery_asset",
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
            name="fk_my_photo_delivery_passenger",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "quality IN ('original', 'optimized')", name="ck_my_photo_delivery_quality"
        ),
        CheckConstraint(
            "content_type IS NULL OR content_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="ck_my_photo_delivery_content_type",
        ),
        CheckConstraint(
            "status IN ('authorizing', 'preparing', 'available', 'expired', 'failed', 'cancelled')",
            name="ck_my_photo_delivery_status",
        ),
        CheckConstraint(
            "expected_size_bytes IS NULL OR expected_size_bytes BETWEEN 1 "
            f"AND {MAX_MY_PHOTOS_MEDIA_BYTES}",
            name="ck_my_photo_delivery_size",
        ),
        CheckConstraint(
            "checksum_sha256 IS NULL OR "
            "(length(checksum_sha256) = 64 AND checksum_sha256 = lower(checksum_sha256))",
            name="ck_my_photo_delivery_checksum",
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)",
            name="ck_my_photo_delivery_fingerprint",
        ),
        CheckConstraint(
            "transport IN ('unavailable', 'development_fixture', 'direct_object_storage')",
            name="ck_my_photo_delivery_transport",
        ),
        CheckConstraint(
            "(status = 'authorizing' AND claim_token IS NOT NULL AND claim_expires_at IS NOT NULL) "
            "OR (status != 'authorizing' AND claim_token IS NULL AND claim_expires_at IS NULL)",
            name="ck_my_photo_delivery_claim",
        ),
        CheckConstraint(
            "(status = 'available' AND provider_authorization_reference IS NOT NULL "
            "AND expected_size_bytes IS NOT NULL AND checksum_sha256 IS NOT NULL "
            "AND content_type IS NOT NULL AND expires_at IS NOT NULL "
            "AND transport != 'unavailable') OR "
            "(status != 'available' AND provider_authorization_reference IS NULL "
            "AND expected_size_bytes IS NULL AND checksum_sha256 IS NULL "
            "AND content_type IS NULL AND expires_at IS NULL "
            "AND supports_ranges = false AND transport = 'unavailable')",
            name="ck_my_photo_delivery_available",
        ),
        Index("ix_my_photo_delivery_expiry", "status", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    passenger_identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passenger_submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    media_asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    quality: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    delivery_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1"
    )
    provider_authorization_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    transport: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unavailable", server_default="unavailable"
    )
    claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expected_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supports_ranges: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stable_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
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


__all__ = [
    "MyPhotoAssetVariantModel",
    "MyPhotoDeliveryAuthorizationModel",
    "MyPhotoEnrollmentModel",
    "MyPhotoFaceOccurrenceModel",
    "MyPhotoGalleryModel",
    "MyPhotoJobModel",
    "MyPhotoLivenessSessionModel",
    "MyPhotoMatchModel",
    "MyPhotoMediaAssetModel",
    "MyPhotoSearchRunModel",
]
