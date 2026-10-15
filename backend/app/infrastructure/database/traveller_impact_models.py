"""Reference-only operational review tasks and company-local publication order."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base
from app.infrastructure.database.traveller_model_support import TravellerRecord, company_scope


class TravellerChangeFeedModel(Base):
    __tablename__ = "traveller_change_feeds"
    __table_args__ = (company_scope("traveller_change_feed"), CheckConstraint("last_sequence >= 0", name="ck_traveller_feed_sequence"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")


class TravellerDocumentReviewTaskModel(TravellerRecord, Base):
    __tablename__ = "traveller_document_review_tasks"
    __table_args__ = (
        company_scope("traveller_document_review_task"),
        ForeignKeyConstraint(["event_id", "agency_id", "company_id"],
            ["traveller_change_events.id", "traveller_change_events.agency_id", "traveller_change_events.company_id"],
            name="fk_traveller_review_event_scope", ondelete="RESTRICT"),
        ForeignKeyConstraint(["participation_id", "agency_id", "company_id"],
            ["traveller_participations.id", "traveller_participations.agency_id", "traveller_participations.company_id"],
            name="fk_traveller_review_participation_scope", ondelete="RESTRICT"),
        ForeignKeyConstraint(["old_document_revision_id", "agency_id", "company_id"],
            ["traveller_document_revisions.id", "traveller_document_revisions.agency_id", "traveller_document_revisions.company_id"],
            name="fk_traveller_review_old_document_scope", ondelete="RESTRICT"),
        ForeignKeyConstraint(["new_document_revision_id", "agency_id", "company_id"],
            ["traveller_document_revisions.id", "traveller_document_revisions.agency_id", "traveller_document_revisions.company_id"],
            name="fk_traveller_review_new_document_scope", ondelete="RESTRICT"),
        UniqueConstraint("event_id", "participation_id", name="uq_traveller_review_event_participation"),
        CheckConstraint("status IN ('pending','resolved','dismissed')", name="ck_traveller_review_status"),
        CheckConstraint("revision >= 1 AND expected_participation_revision >= 1", name="ck_traveller_review_revisions"),
        CheckConstraint("status = 'pending' OR (resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL AND resolution_reason IS NOT NULL)", name="ck_traveller_review_resolution"),
        Index("ix_traveller_review_queue", "agency_id", "company_id", "status", "created_at", "id"),
        Index("ix_traveller_review_participation", "participation_id", "status", "id"),
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    participation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    old_document_revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    new_document_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    expected_participation_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    resolution_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
