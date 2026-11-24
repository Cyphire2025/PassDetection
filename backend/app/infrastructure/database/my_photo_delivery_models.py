"""Short-lived passenger delivery grants with fenced provider claims."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.application.my_photos.limits import MAX_MY_PHOTOS_MEDIA_BYTES
from app.infrastructure.database.model_base import Base, _utcnow


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
