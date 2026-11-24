"""Resolved or reviewable deadline provenance tied to the exact analysis owner."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.email_ai_models import _utcnow
from app.infrastructure.database.model_base import JSONB, Base


class EmailDetectedDeadlineModel(Base):
    __module__ = "app.infrastructure.database.email_ai_models"
    __tablename__ = "email_detected_deadlines"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "source_fingerprint",
            name="uq_email_deadline_source",
        ),
        ForeignKeyConstraint(
            [
                "analysis_id",
                "message_id",
                "connection_id",
                "agency_id",
                "owner_user_id",
            ],
            [
                "email_ai_analyses.id",
                "email_ai_analyses.message_id",
                "email_ai_analyses.connection_id",
                "email_ai_analyses.agency_id",
                "email_ai_analyses.owner_user_id",
            ],
            name="fk_email_deadline_analysis_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('detected', 'review_required', 'acknowledged', 'completed', 'dismissed')",
            name="ck_email_deadline_status",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_email_deadline_confidence",
        ),
        Index(
            "ix_email_deadline_owner_due",
            "owner_user_id",
            "status",
            "due_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    analysis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    deadline_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_phrase: Mapped[str] = mapped_column(String(500), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    is_ambiguous: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="detected", server_default="detected"
    )
    resolution_evidence: Mapped[dict[str, object]] = mapped_column(
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
