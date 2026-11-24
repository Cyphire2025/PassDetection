"""Immutable photo assets and versioned private delivery derivatives."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
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
