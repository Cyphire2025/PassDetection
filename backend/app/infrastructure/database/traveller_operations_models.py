"""Resumable reconciliation and revision events contain references, never proof answers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base
from app.infrastructure.database.traveller_model_support import (
    TravellerRecord,
    company_scope,
    group_scope,
    record_scope,
    traveller_scope,
)

IMPACT_QUEUE_FILTER = "processed_at IS NULL AND impact_attempt_count < 5 AND event_type IN ('document_promoted', 'document_blocked')"


class TravellerMatchCaseModel(TravellerRecord, Base):
    __tablename__ = "traveller_match_cases"
    __table_args__ = (
        company_scope("traveller_match_case"),
        group_scope("traveller_match_case"),
        traveller_scope("traveller_match_case"),
        record_scope("traveller_match_case"),
        UniqueConstraint(
            "agency_id",
            "company_id",
            "group_id",
            "source_kind",
            "source_row_key",
            name="uq_traveller_match_source",
        ),
        CheckConstraint(
            "status IN ('pending','provisional','unmatched','ambiguous','conflicting','resolved','purged')",
            name="ck_traveller_match_status",
        ),
        CheckConstraint("revision >= 1", name="ck_traveller_match_revision"),
        Index("ix_traveller_match_queue", "agency_id", "company_id", "group_id", "status", "id"),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    traveller_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_row_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TravellerReconciliationJobModel(TravellerRecord, Base):
    __tablename__ = "traveller_reconciliation_jobs"
    __table_args__ = (
        company_scope("traveller_reconciliation_job"),
        group_scope("traveller_reconciliation_job"),
        record_scope("traveller_reconciliation_job"),
        UniqueConstraint(
            "agency_id",
            "company_id",
            "group_id",
            "idempotency_key",
            name="uq_traveller_reconciliation_idempotency",
        ),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_traveller_reconciliation_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND processed_count >= 0 AND expected_group_revision >= 1",
            name="ck_traveller_reconciliation_counts",
        ),
        Index("ix_traveller_reconciliation_queue", "status", "available_at", "id"),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    cursor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expected_group_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    processed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TravellerChangeEventModel(TravellerRecord, Base):
    __tablename__ = "traveller_change_events"
    __table_args__ = (
        company_scope("traveller_change_event"),
        traveller_scope("traveller_change_event"),
        record_scope("traveller_change_event"),
        UniqueConstraint(
            "agency_id", "company_id", "idempotency_key", name="uq_traveller_change_idempotency"
        ),
        CheckConstraint(
            "event_type IN ('added','changed','removed','contact_recovered','document_promoted','document_blocked','reuse_revoked')",
            name="ck_traveller_change_type",
        ),
        Index("ix_traveller_change_cursor", "agency_id", "company_id", "created_at", "id"),
        Index("ix_traveller_change_pending", "processed_at", "created_at", "id"),
        UniqueConstraint("agency_id", "company_id", "feed_sequence", name="uq_traveller_change_feed_sequence"),
        CheckConstraint("impact_attempt_count >= 0 AND (feed_sequence IS NULL OR feed_sequence > 0)", name="ck_traveller_change_processing_counts"),
        Index("ix_traveller_change_unpublished", "feed_sequence", "created_at", "id"),
        Index("ix_traveller_change_unpublished_scope", "agency_id", "company_id", "created_at", "id",
              postgresql_where=text("feed_sequence IS NULL"), sqlite_where=text("feed_sequence IS NULL")),
        Index("ix_traveller_change_impact_queue", "impact_available_at", "id",
              postgresql_where=text(IMPACT_QUEUE_FILTER), sqlite_where=text(IMPACT_QUEUE_FILTER)),
    )
    traveller_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    aggregate_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    feed_sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    impact_cursor: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    impact_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    impact_available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    impact_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
