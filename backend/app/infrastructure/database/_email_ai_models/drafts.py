"""Unsent reply drafts with owner-scoped analysis provenance."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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


class EmailReplyDraftModel(Base):
    __module__ = "app.infrastructure.database.email_ai_models"
    __tablename__ = "email_reply_drafts"
    __table_args__ = (
        UniqueConstraint("analysis_id", name="uq_email_reply_draft_analysis"),
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
            name="fk_email_reply_analysis_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('prepared', 'edited', 'approved', 'dismissed')",
            name="ck_email_reply_draft_status",
        ),
        CheckConstraint("revision >= 1", name="ck_email_reply_draft_revision"),
        Index(
            "ix_email_reply_owner_status",
            "owner_user_id",
            "status",
            "updated_at",
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
    recipients_json: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    subject: Mapped[str] = mapped_column(String(998), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="prepared", server_default="prepared"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    edited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
