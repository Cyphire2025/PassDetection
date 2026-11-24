"""Revisioned email review decisions, evidence, and active queue uniqueness."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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


class EmailReviewItemModel(Base):
    """An exception requiring an explicit, revision-checked staff decision."""
    __module__ = "app.infrastructure.database.email_models"

    __tablename__ = "email_review_items"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", name="uq_email_review_items_id_agency"),
        UniqueConstraint(
            "id",
            "agency_id",
            "owner_user_id",
            name="uq_email_review_items_id_agency_owner",
        ),
        UniqueConstraint(
            "id",
            "message_id",
            "agency_id",
            name="uq_email_review_items_id_message_agency",
        ),
        UniqueConstraint(
            "id",
            "message_id",
            "agency_id",
            "owner_user_id",
            name="uq_email_review_items_id_message_agency_owner",
        ),
        UniqueConstraint(
            "resolution_request_id",
            name="uq_email_review_items_resolution_request",
        ),
        ForeignKeyConstraint(
            ["message_id", "agency_id"],
            ["email_messages.id", "email_messages.agency_id"],
            name="fk_email_review_items_message_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["message_id", "agency_id", "owner_user_id"],
            [
                "email_messages.id",
                "email_messages.agency_id",
                "email_messages.owner_user_id",
            ],
            name="fk_email_review_items_message_agency_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "message_id", "agency_id"],
            [
                "email_artifacts.id",
                "email_artifacts.message_id",
                "email_artifacts.agency_id",
            ],
            name="fk_email_review_items_artifact_message_agency",
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
            name="fk_email_review_items_artifact_message_agency_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "review_type IN ("
            "'relevance', 'retrieval', 'group_match', 'passenger_match', "
            "'document_conflict', 'possible_revision', 'traveller_replacement', "
            "'contact_change', 'processing_failure'"
            ")",
            name="ck_email_review_items_review_type",
        ),
        CheckConstraint(
            "status IN ('open', 'deferred', 'resolved', 'rejected', 'cancelled')",
            name="ck_email_review_items_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_email_review_items_confidence",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_email_review_items_revision",
        ),
        CheckConstraint(
            "(status IN ('resolved', 'rejected', 'cancelled') "
            "AND resolved_at IS NOT NULL) OR "
            "(status IN ('open', 'deferred') AND resolved_at IS NULL)",
            name="ck_email_review_items_resolution_state",
        ),
        CheckConstraint(
            "status != 'deferred' OR deferred_until IS NOT NULL",
            name="ck_email_review_items_deferred_until",
        ),
        Index(
            "uq_email_review_items_active_message",
            "agency_id",
            "message_id",
            "review_type",
            unique=True,
            postgresql_where=text("artifact_id IS NULL AND status IN ('open', 'deferred')"),
            sqlite_where=text("artifact_id IS NULL AND status IN ('open', 'deferred')"),
        ),
        Index(
            "uq_email_review_items_active_artifact",
            "agency_id",
            "artifact_id",
            "review_type",
            unique=True,
            postgresql_where=text("artifact_id IS NOT NULL AND status IN ('open', 'deferred')"),
            sqlite_where=text("artifact_id IS NOT NULL AND status IN ('open', 'deferred')"),
        ),
        Index(
            "ix_email_review_items_agency_queue",
            "agency_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_email_review_items_owner_queue",
            "owner_user_id",
            "status",
            "created_at",
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
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    review_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="open",
        server_default="open",
    )
    proposed_action: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    conflicts: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    alternatives: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    proposed_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    candidate_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    candidate_passenger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="SET NULL"),
        nullable=True,
    )
    selected_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    selected_passenger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="SET NULL"),
        nullable=True,
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    resolution_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolution_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    deferred_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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
