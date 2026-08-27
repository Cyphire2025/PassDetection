"""SQLAlchemy model for the common passport image library."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base, _utcnow


class PassportImageLibraryItemModel(Base):
    __tablename__ = "passport_image_library_items"
    __table_args__ = (
        CheckConstraint(
            "image_type IN ('visa_photo', 'passport_front', 'passport_back')",
            name="ck_passport_image_library_items_type",
        ),
        CheckConstraint(
            "source IN ('original', 'manual', 'ai_generated')",
            name="ck_passport_image_library_items_source",
        ),
        UniqueConstraint(
            "submission_id",
            "image_type",
            "storage_key",
            name="uq_passport_image_library_items_storage",
        ),
        Index(
            "ix_passport_image_library_items_submission_type_created",
            "submission_id",
            "image_type",
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
    image_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    original_source_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    prompt_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
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
