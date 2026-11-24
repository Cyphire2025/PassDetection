"""Public upload qualifier receipts and persisted extraction job state."""

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
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base, _utcnow


class QualifierSelectionModel(Base):
    __module__ = "app.infrastructure.database.models"
    __tablename__ = "qualifier_selections"
    __table_args__ = (
        CheckConstraint(
            "("
            "is_self = true AND relation_code IS NULL AND relation_label = 'Self'"
            ") OR ("
            "is_self = false AND relation_code IS NOT NULL AND relation_label <> 'Self'"
            ")",
            name="ck_qualifier_selections_choice",
        ),
        CheckConstraint(
            "expires_at > selected_at",
            name="ck_qualifier_selections_expiry",
        ),
        CheckConstraint(
            "relation_code IS NULL OR relation_code IN ("
            "'spouse', 'husband', 'wife', 'brother', 'sister', 'son', "
            "'daughter', 'father', 'mother', 'parent', 'child', "
            "'grandfather', 'grandmother', 'grandson', 'granddaughter', "
            "'father_in_law', 'mother_in_law', 'brother_in_law', "
            "'sister_in_law', 'son_in_law', 'daughter_in_law', "
            "'legal_guardian', 'other'"
            ")",
            name="ck_qualifier_selections_relation_code",
        ),
        CheckConstraint(
            "relation_code <> 'other' OR ("
            "length(trim(relation_label)) BETWEEN 1 AND 100 AND "
            "lower(trim(relation_label)) <> 'self')",
            name="ck_qualifier_selections_other_text",
        ),
        Index(
            "ix_qualifier_selections_group_expires",
            "group_id",
            "expires_at",
        ),
        UniqueConstraint(
            "id",
            "group_id",
            name="uq_qualifier_selections_id_group",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    is_self: Mapped[bool] = mapped_column(Boolean, nullable=False)
    relation_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    relation_label: Mapped[str] = mapped_column(String(100), nullable=False)
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )


class PassportProcessingJobModel(Base):
    __module__ = "app.infrastructure.database.models"
    __tablename__ = "passport_processing_jobs"
    __table_args__ = (
        CheckConstraint(
            "extraction_revision >= 0",
            name="ck_passport_processing_jobs_extraction_revision",
        ),
        Index(
            "uq_passport_processing_jobs_active_revision",
            "submission_id",
            "extraction_revision",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index(
            "ix_passport_processing_jobs_status_created_at",
            "status",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    queue_name: Mapped[str] = mapped_column(String(64), nullable=False, default="passport_ocr")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    extraction_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    current_stage: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
