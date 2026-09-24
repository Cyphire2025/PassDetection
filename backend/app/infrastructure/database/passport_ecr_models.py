"""Current ECR outcome bound to one finalized passport back-page source."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base, _utcnow


class PassportEcrCheckModel(Base):
    __tablename__ = "passport_ecr_checks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','processing','completed','failed','disabled')",
            name="ck_passport_ecr_status",
        ),
        CheckConstraint(
            "result IS NULL OR result IN ('ECR','NA','NEEDS_REVIEW')", name="ck_passport_ecr_result"
        ),
        Index("ix_passport_ecr_recovery", "status", "next_attempt_at", "lease_expires_at"),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    generation: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    source_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    result: Mapped[str | None] = mapped_column(String(24), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
