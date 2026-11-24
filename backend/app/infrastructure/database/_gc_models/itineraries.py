"""Versioned group itineraries, schedule days, and ordered items."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.gc_mobile_models import _utcnow
from app.infrastructure.database.model_base import JSONB, Base


class GCItineraryVersionModel(Base):
    """A complete immutable itinerary snapshot with draft/publish lifecycle."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "gc_itinerary_versions"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            name="uq_gc_itinerary_version_scope",
        ),
        UniqueConstraint("gc_group_access_id", "version", name="uq_gc_itinerary_version_number"),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_gc_itinerary_version_access",
            ondelete="CASCADE",
        ),
        CheckConstraint("version >= 1", name="ck_gc_itinerary_version_number"),
        CheckConstraint("revision >= 1", name="ck_gc_itinerary_version_revision"),
        CheckConstraint(
            "status IN ('draft', 'published', 'retired')",
            name="ck_gc_itinerary_version_status",
        ),
        CheckConstraint(
            "availability_expires_at IS NULL OR availability_starts_at IS NULL "
            "OR availability_expires_at > availability_starts_at",
            name="ck_gc_itinerary_version_window",
        ),
        CheckConstraint(
            "(status = 'draft' AND published_at IS NULL) OR "
            "(status IN ('published', 'retired') AND published_at IS NOT NULL)",
            name="ck_gc_itinerary_publish_shape",
        ),
        CheckConstraint(
            "content_checksum IS NULL OR length(content_checksum) = 64",
            name="ck_gc_itinerary_checksum",
        ),
        CheckConstraint(
            "status = 'draft' OR content_checksum IS NOT NULL",
            name="ck_gc_itinerary_published_checksum",
        ),
        Index(
            "uq_gc_itinerary_published",
            "gc_group_access_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
            sqlite_where=text("status = 'published'"),
        ),
        Index(
            "ix_gc_itinerary_access_status",
            "gc_group_access_id",
            "status",
            "version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    destination_information: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    availability_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    availability_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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


class GCItineraryDayModel(Base):
    """One ordered day within a versioned structured itinerary."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "gc_itinerary_days"
    __table_args__ = (
        UniqueConstraint(
            "itinerary_version_id",
            "day_number",
            name="uq_gc_itinerary_day_number",
        ),
        UniqueConstraint(
            "id",
            "itinerary_version_id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            name="uq_gc_itinerary_day_scope",
        ),
        ForeignKeyConstraint(
            [
                "itinerary_version_id",
                "gc_group_access_id",
                "agency_id",
                "group_id",
            ],
            [
                "gc_itinerary_versions.id",
                "gc_itinerary_versions.gc_group_access_id",
                "gc_itinerary_versions.agency_id",
                "gc_itinerary_versions.group_id",
            ],
            name="fk_gc_itinerary_day_version",
            ondelete="CASCADE",
        ),
        CheckConstraint("day_number >= 1", name="ck_gc_itinerary_day_number"),
        CheckConstraint("sort_order >= 0", name="ck_gc_itinerary_day_sort"),
        Index(
            "ix_gc_itinerary_day_order",
            "itinerary_version_id",
            "sort_order",
            "day_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    itinerary_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    day_number: Mapped[int] = mapped_column(Integer, nullable=False)
    trip_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
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


class GCItineraryItemModel(Base):
    """A bounded, typed schedule item suitable for compact mobile manifests."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "gc_itinerary_items"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "itinerary_day_id",
                "itinerary_version_id",
                "gc_group_access_id",
                "agency_id",
                "group_id",
            ],
            [
                "gc_itinerary_days.id",
                "gc_itinerary_days.itinerary_version_id",
                "gc_itinerary_days.gc_group_access_id",
                "gc_itinerary_days.agency_id",
                "gc_itinerary_days.group_id",
            ],
            name="fk_gc_itinerary_item_day",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["common_document_id", "gc_group_access_id", "agency_id", "group_id"],
            [
                "gc_common_documents.id",
                "gc_common_documents.gc_group_access_id",
                "gc_common_documents.agency_id",
                "gc_common_documents.group_id",
            ],
            name="fk_gc_itinerary_item_document",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "item_type IN ('travel', 'flight', 'transfer', 'hotel', 'meal', 'meeting', "
            "'activity', 'conference', 'free_time', 'instruction', 'other')",
            name="ck_gc_itinerary_item_type",
        ),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at >= starts_at",
            name="ck_gc_itinerary_item_window",
        ),
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="ck_gc_itinerary_item_latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="ck_gc_itinerary_item_longitude",
        ),
        CheckConstraint("sort_order >= 0", name="ck_gc_itinerary_item_sort"),
        Index("ix_gc_itinerary_item_order", "itinerary_day_id", "sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    itinerary_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    itinerary_day_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    common_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    item_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="activity", server_default="activity"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_all_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    location_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_address: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    map_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_important: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    public_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
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
