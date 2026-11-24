"""Versioned passenger searches, match results and durable feedback."""

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
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base, _utcnow


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
