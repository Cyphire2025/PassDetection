"""Sanitized, owner-scoped email processing activity and provenance."""

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

from app.infrastructure.database.email_models import _utcnow
from app.infrastructure.database.model_base import JSONB, Base


class EmailActivityEventModel(Base):
    """Append-only, sanitized operational trace for one email workflow."""
    __module__ = "app.infrastructure.database.email_models"

    __tablename__ = "email_activity_events"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "event_key",
            name="uq_email_activity_events_agency_event_key",
        ),
        ForeignKeyConstraint(
            ["connection_id", "agency_id"],
            ["email_connections.id", "email_connections.agency_id"],
            name="fk_email_activity_events_connection_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["connection_id", "agency_id", "owner_user_id"],
            [
                "email_connections.id",
                "email_connections.agency_id",
                "email_connections.owner_user_id",
            ],
            name="fk_email_activity_events_connection_agency_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["message_id", "connection_id", "agency_id"],
            [
                "email_messages.id",
                "email_messages.connection_id",
                "email_messages.agency_id",
            ],
            name="fk_email_activity_events_message_connection_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["message_id", "connection_id", "agency_id", "owner_user_id"],
            [
                "email_messages.id",
                "email_messages.connection_id",
                "email_messages.agency_id",
                "email_messages.owner_user_id",
            ],
            name="fk_email_activity_events_message_connection_agency_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "message_id", "agency_id"],
            [
                "email_artifacts.id",
                "email_artifacts.message_id",
                "email_artifacts.agency_id",
            ],
            name="fk_email_activity_events_artifact_message_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "message_id", "agency_id", "owner_user_id"],
            [
                "email_artifacts.id",
                "email_artifacts.message_id",
                "email_artifacts.agency_id",
                "email_artifacts.owner_user_id",
            ],
            name="fk_email_activity_events_artifact_message_agency_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["review_item_id", "message_id", "agency_id"],
            [
                "email_review_items.id",
                "email_review_items.message_id",
                "email_review_items.agency_id",
            ],
            name="fk_email_activity_events_review_message_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["review_item_id", "message_id", "agency_id", "owner_user_id"],
            [
                "email_review_items.id",
                "email_review_items.message_id",
                "email_review_items.agency_id",
                "email_review_items.owner_user_id",
            ],
            name="fk_email_activity_events_review_message_agency_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "stage IN ('info', 'success', 'warning', 'failure')",
            name="ck_email_activity_events_stage",
        ),
        CheckConstraint(
            "actor_type IN ('system', 'user', 'provider')",
            name="ck_email_activity_events_actor_type",
        ),
        CheckConstraint(
            "actor_type = 'user' OR actor_user_id IS NULL",
            name="ck_email_activity_events_actor",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_email_activity_events_confidence",
        ),
        CheckConstraint(
            "artifact_id IS NULL OR message_id IS NOT NULL",
            name="ck_email_activity_events_artifact_message",
        ),
        CheckConstraint(
            "review_item_id IS NULL OR message_id IS NOT NULL",
            name="ck_email_activity_events_review_message",
        ),
        CheckConstraint(
            "ai_used OR (ai_provider IS NULL AND ai_model IS NULL)",
            name="ck_email_activity_events_ai_metadata",
        ),
        Index(
            "ix_email_activity_events_agency_occurred",
            "agency_id",
            "occurred_at",
        ),
        Index(
            "ix_email_activity_events_owner_occurred",
            "owner_user_id",
            "occurred_at",
        ),
        Index(
            "ix_email_activity_events_message_occurred",
            "message_id",
            "occurred_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    review_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="system",
        server_default="system",
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    summary_code: Mapped[str] = mapped_column(String(100), nullable=False)
    # Sanitized structured metadata only: never raw message bodies, tokens, or URLs.
    details: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    ai_used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    ai_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    changed_entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    changed_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
