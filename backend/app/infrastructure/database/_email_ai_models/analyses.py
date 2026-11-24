"""Owner-scoped analysis results, durable attempts and claim leases."""

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
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.email_ai_models import _utcnow
from app.infrastructure.database.model_base import JSONB, Base


class EmailAiAnalysisModel(Base):
    __module__ = "app.infrastructure.database.email_ai_models"
    __tablename__ = "email_ai_analyses"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "input_hash",
            "prompt_schema_version",
            name="uq_email_ai_analysis_input",
        ),
        UniqueConstraint(
            "id",
            "message_id",
            "connection_id",
            "agency_id",
            "owner_user_id",
            name="uq_email_ai_analysis_owner",
        ),
        ForeignKeyConstraint(
            ["message_id", "connection_id", "agency_id", "owner_user_id"],
            [
                "email_messages.id",
                "email_messages.connection_id",
                "email_messages.agency_id",
                "email_messages.owner_user_id",
            ],
            name="fk_email_ai_analysis_message_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', "
            "'review_required', 'failed', 'ignored')",
            name="ck_email_ai_analysis_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_email_ai_analysis_confidence",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_email_ai_analysis_attempts",
        ),
        CheckConstraint(
            "(lease_token IS NULL) = (lease_expires_at IS NULL)",
            name="ck_email_ai_analysis_lease",
        ),
        Index(
            "ix_email_ai_analysis_owner_queue",
            "owner_user_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_email_ai_analysis_pending",
            "status",
            "lease_expires_at",
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
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", server_default="pending"
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_version: Mapped[str] = mapped_column(String(32), nullable=False)
    ai_provider: Mapped[str] = mapped_column(
        String(40), nullable=False, default="google", server_default="google"
    )
    ai_model: Mapped[str] = mapped_column(String(128), nullable=False)
    intent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_attention: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    result_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    context_manifest: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    lease_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
