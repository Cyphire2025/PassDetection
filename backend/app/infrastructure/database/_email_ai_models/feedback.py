"""Owner-scoped AI review feedback and typed correction provenance."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.email_ai_models import _utcnow
from app.infrastructure.database.model_base import JSONB, Base


class EmailAiFeedbackModel(Base):
    __module__ = "app.infrastructure.database.email_ai_models"
    __tablename__ = "email_ai_feedback"
    __table_args__ = (
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
            name="fk_email_feedback_analysis_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "feedback_type IN ('correction', 'confirmation', 'dismissal')",
            name="ck_email_feedback_type",
        ),
        Index(
            "ix_email_feedback_owner_created",
            "owner_user_id",
            "created_at",
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
    feedback_type: Mapped[str] = mapped_column(String(24), nullable=False)
    field_name: Mapped[str] = mapped_column(String(80), nullable=False)
    original_value: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    corrected_value: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
