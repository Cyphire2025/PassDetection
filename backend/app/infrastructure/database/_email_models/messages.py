"""Owner-scoped provider message metadata and processing progress."""

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

from app.infrastructure.database.email_models import _utcnow
from app.infrastructure.database.model_base import JSONB, Base


class EmailMessageModel(Base):
    """A normalized provider message with minimal retained content."""
    __module__ = "app.infrastructure.database.email_models"

    __tablename__ = "email_messages"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "provider_message_id",
            name="uq_email_messages_connection_provider_message",
        ),
        UniqueConstraint("id", "agency_id", name="uq_email_messages_id_agency"),
        UniqueConstraint(
            "id",
            "agency_id",
            "owner_user_id",
            name="uq_email_messages_id_agency_owner",
        ),
        UniqueConstraint(
            "id",
            "connection_id",
            "agency_id",
            name="uq_email_messages_id_connection_agency",
        ),
        UniqueConstraint(
            "id",
            "connection_id",
            "agency_id",
            "owner_user_id",
            name="uq_email_messages_id_connection_agency_owner",
        ),
        ForeignKeyConstraint(
            ["connection_id", "agency_id"],
            ["email_connections.id", "email_connections.agency_id"],
            name="fk_email_messages_connection_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["connection_id", "agency_id", "owner_user_id"],
            [
                "email_connections.id",
                "email_connections.agency_id",
                "email_connections.owner_user_id",
            ],
            name="fk_email_messages_connection_agency_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "relevance_status IN ('pending', 'relevant', 'possible', 'ignored', 'failed')",
            name="ck_email_messages_relevance_status",
        ),
        CheckConstraint(
            "processing_status IN ("
            "'discovered', 'queued', 'processing', 'completed', "
            "'partially_completed', 'review_required', 'failed', 'ignored'"
            ")",
            name="ck_email_messages_processing_status",
        ),
        CheckConstraint(
            "relevance_confidence IS NULL OR "
            "(relevance_confidence >= 0 AND relevance_confidence <= 1)",
            name="ck_email_messages_relevance_confidence",
        ),
        CheckConstraint(
            "artifact_count >= 0 AND processed_artifact_count >= 0 AND review_count >= 0",
            name="ck_email_messages_counts",
        ),
        Index(
            "ix_email_messages_agency_received",
            "agency_id",
            "received_at",
        ),
        Index(
            "ix_email_messages_owner_received",
            "owner_user_id",
            "received_at",
        ),
        Index(
            "ix_email_messages_agency_processing",
            "agency_id",
            "processing_status",
            "received_at",
        ),
        Index(
            "ix_email_messages_connection_thread",
            "connection_id",
            "thread_id",
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
    provider_message_id: Mapped[str] = mapped_column(String(512), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    provider_history_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    internet_message_id: Mapped[str | None] = mapped_column(String(998), nullable=True)
    sender_address: Mapped[str | None] = mapped_column(String(320), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipients_json: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    label_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    has_attachments: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    relevance_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    relevance_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_json: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    processing_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="discovered",
        server_default="discovered",
    )
    artifact_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    processed_artifact_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    review_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    ai_used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
