"""Bounded durable photo jobs, leases and publication progress."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
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

from app.infrastructure.database.model_base import Base, _utcnow


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
