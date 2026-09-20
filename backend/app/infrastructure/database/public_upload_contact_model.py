"""One rotating, submission-scoped WhatsApp contact proof per public upload."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base


class PublicUploadContactChallengeModel(Base):
    __tablename__ = "public_upload_contact_challenges"
    __table_args__ = (
        UniqueConstraint("id", name="uq_public_upload_contact_challenge_id"),
        CheckConstraint(
            "status IN ('sending', 'pending', 'failed', 'locked', 'verified', 'consumed')",
            name="ck_public_upload_contact_challenge_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_public_upload_contact_attempts"),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False,
    )
    upload_session_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resend_available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proof_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
