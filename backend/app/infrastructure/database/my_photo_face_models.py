"""Tenant-scoped provider face occurrences and canonical geometry."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base, _utcnow


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
