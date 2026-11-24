"""Revisioned passport image derivatives and queued Visa-photo variants."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base, _utcnow


class PassportImageCropModel(Base):
    """Non-destructive image-edit metadata and its revisioned display derivative."""
    __module__ = "app.infrastructure.database.models"

    __tablename__ = "passport_image_crops"
    __table_args__ = (
        UniqueConstraint(
            "submission_id", "image_type", name="uq_passport_image_crops_submission_type"
        ),
        CheckConstraint(
            "image_type IN ('visa_photo', 'passport_front', 'passport_back', "
            "'passport_cover', 'passport_back_cover')",
            name="ck_passport_image_crops_type",
        ),
        CheckConstraint(
            "rotation_degrees >= 0 AND rotation_degrees <= 359",
            name="ck_passport_image_crops_rotation",
        ),
        CheckConstraint(
            "crop_x >= 0 AND crop_y >= 0 AND crop_width >= 0.08 AND crop_height >= 0.08 "
            "AND crop_x + crop_width <= 1.000001 AND crop_y + crop_height <= 1.000001",
            name="ck_passport_image_crops_bounds",
        ),
        CheckConstraint(
            "source_width > 0 AND source_height > 0", name="ck_passport_image_crops_source_size"
        ),
        CheckConstraint(
            "sharpness >= 1.0 AND sharpness <= 3.0",
            name="ck_passport_image_crops_sharpness",
        ),
        CheckConstraint(
            "sharpness_algorithm_version IN (1, 2)",
            name="ck_passport_image_crops_sharpness_algorithm_version",
        ),
        CheckConstraint("revision > 0", name="ck_passport_image_crops_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    image_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    edit_source_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    derived_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    crop_x: Mapped[float] = mapped_column(Float, nullable=False)
    crop_y: Mapped[float] = mapped_column(Float, nullable=False)
    crop_width: Mapped[float] = mapped_column(Float, nullable=False)
    crop_height: Mapped[float] = mapped_column(Float, nullable=False)
    rotation_degrees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sharpness: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
        server_default="1.0",
    )
    sharpness_algorithm_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    source_width: Mapped[int] = mapped_column(Integer, nullable=False)
    source_height: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PassportVisaAiImageModel(Base):
    """Durable AI variants for one submission's Visa photograph."""
    __module__ = "app.infrastructure.database.models"

    __tablename__ = "passport_visa_ai_images"
    __table_args__ = (
        Index(
            "ix_passport_visa_ai_images_submission_created",
            "submission_id",
            "created_at",
        ),
        UniqueConstraint(
            "submission_id",
            "generated_storage_key",
            name="uq_passport_visa_ai_images_submission_storage_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_source_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    input_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    generated_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    prompt: Mapped[str] = mapped_column(String(1000), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )


class PassportVisaAiImageJobModel(Base):
    """Durable queue state for slow Visa-photo AI generation."""
    __module__ = "app.infrastructure.database.models"

    __tablename__ = "passport_visa_ai_image_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_passport_visa_ai_image_jobs_status",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="ck_passport_visa_ai_image_jobs_attempts",
        ),
        CheckConstraint(
            "max_attempts BETWEEN 1 AND 3",
            name="ck_passport_visa_ai_image_jobs_max_attempts",
        ),
        Index(
            "uq_passport_visa_ai_image_jobs_active_submission",
            "submission_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index(
            "ix_passport_visa_ai_image_jobs_submission_created",
            "submission_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_source_storage_key: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    input_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    prompt: Mapped[str] = mapped_column(String(1000), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="queued",
        server_default="queued",
        index=True,
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2,
        server_default="2",
    )
    celery_task_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    result_image_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_visa_ai_images.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(320), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )
