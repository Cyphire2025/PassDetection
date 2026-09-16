"""Authored alerts preserve explicit batches and all original recipient grants."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class GCNotificationDraftModel(Base):
    __tablename__ = "gc_notification_drafts"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", name="uq_gc_notification_draft_scope"),
        CheckConstraint("revision >= 1", name="ck_gc_notification_draft_revision"),
        CheckConstraint("status IN ('draft', 'sent')", name="ck_gc_notification_draft_status"),
        CheckConstraint(
            "audience IN ('all_active_trips', 'selected_groups')",
            name="ck_gc_notification_draft_audience",
        ),
        CheckConstraint(
            "length(trim(title)) BETWEEN 1 AND 100 AND length(trim(body)) BETWEEN 1 AND 240",
            name="ck_gc_notification_draft_content",
        ),
        Index("ix_gc_notification_draft_page", "agency_id", "id"),
        Index(
            "ix_gc_notification_saved_page",
            "agency_id",
            "created_at",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[str] = mapped_column(String(240), nullable=False)
    audience: Mapped[str] = mapped_column(String(24), nullable=False)
    group_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    group_names: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Removing a saved message must never erase a send, its recipients or delivery evidence.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_gc_notification_draft_deleted_by", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class GCNotificationBatchModel(Base):
    __tablename__ = "gc_notification_batches"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", name="uq_gc_notification_batch_scope"),
        UniqueConstraint("agency_id", "request_id", name="uq_gc_notification_batch_request"),
        ForeignKeyConstraint(
            ["draft_id", "agency_id"],
            ["gc_notification_drafts.id", "gc_notification_drafts.agency_id"],
            name="fk_gc_notification_batch_draft",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "draft_revision >= 1 AND length(request_fingerprint) = 64",
            name="ck_gc_notification_batch_request",
        ),
        CheckConstraint("expires_at > created_at", name="ck_gc_notification_batch_expiry"),
        CheckConstraint(
            "audience IN ('all_active_trips', 'selected_groups')",
            name="ck_gc_notification_batch_audience",
        ),
        CheckConstraint(
            "length(trim(title)) BETWEEN 1 AND 100 AND length(trim(body)) BETWEEN 1 AND 240",
            name="ck_gc_notification_batch_content",
        ),
        Index("ix_gc_notification_batch_page", "agency_id", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[str] = mapped_column(String(240), nullable=False)
    audience: Mapped[str] = mapped_column(String(24), nullable=False)
    group_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    group_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    role_counts: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GCNotificationRecipientModel(Base):
    __tablename__ = "gc_notification_recipients"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", name="uq_gc_notification_recipient_scope"),
        UniqueConstraint("batch_id", "person_key", name="uq_gc_notification_batch_person"),
        ForeignKeyConstraint(
            ["batch_id", "agency_id"],
            ["gc_notification_batches.id", "gc_notification_batches.agency_id"],
            name="fk_gc_notification_recipient_batch",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "recipient_type IN ('passenger', 'client_manager', 'coordinator')",
            name="ck_gc_notification_recipient_type",
        ),
        Index("ix_gc_notification_recipient_batch", "agency_id", "batch_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    recipient_type: Mapped[str] = mapped_column(String(24), nullable=False)
    # Passengers use a keyed hash of the collection contact; never store raw phone numbers here.
    person_key: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class GCNotificationRecipientGrantModel(Base):
    __tablename__ = "gc_notification_recipient_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["recipient_id", "agency_id"],
            ["gc_notification_recipients.id", "gc_notification_recipients.agency_id"],
            name="fk_gc_notification_grant_recipient",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "recipient_id", "group_id", "principal_id", name="uq_gc_notification_recipient_grant"
        ),
        CheckConstraint(
            "access_generation >= 0 AND (identity_claim_generation IS NULL OR identity_claim_generation >= 0)",
            name="ck_gc_notification_grant_generations",
        ),
        Index("ix_gc_notification_grant_principal", "agency_id", "principal_id", "recipient_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    recipient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Frozen historical identifiers intentionally survive deletion of one trip/identity.
    # Every access recheck joins current tenant-scoped rows; missing grants never authorize.
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    access_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    identity_claim_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
