"""Auditable upload-to-broadcast roster replacement and rejection receipts."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class PassportRosterResolutionModel(Base):
    """Auditable resolution of an upload that did not match a broadcast recipient."""
    __module__ = "app.infrastructure.database.models"

    __tablename__ = "passport_roster_resolutions"
    __table_args__ = (
        UniqueConstraint(
            "client_group_id",
            "request_id",
            name="uq_passport_roster_resolution_group_request",
        ),
        CheckConstraint(
            "resolution_type IN ('replacement', 'rejected')",
            name="ck_passport_roster_resolution_type",
        ),
        CheckConstraint(
            "status IN ('active', 'restored')",
            name="ck_passport_roster_resolution_status",
        ),
        CheckConstraint(
            "(status = 'active' AND restored_at IS NULL) "
            "OR (status = 'restored' AND restored_at IS NOT NULL)",
            name="ck_passport_roster_resolution_restored_at",
        ),
        CheckConstraint(
            "(resolution_type = 'replacement' "
            "AND replaced_recipient_normalized_phone IS NOT NULL "
            "AND original_recipient_phone IS NOT NULL "
            "AND (status = 'restored' OR broadcast_recipient_id IS NOT NULL)) "
            "OR (resolution_type = 'rejected' "
            "AND broadcast_recipient_id IS NULL "
            "AND replaced_recipient_normalized_phone IS NULL)",
            name="ck_passport_roster_resolution_recipient",
        ),
        Index(
            "ix_passport_roster_resolutions_group_status_created",
            "client_group_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_passport_roster_resolutions_active_phone",
            "agency_id",
            "client_group_id",
            "replaced_recipient_normalized_phone",
            postgresql_where=text("status = 'active' AND resolution_type = 'replacement'"),
            sqlite_where=text("status = 'active' AND resolution_type = 'replacement'"),
        ),
        Index(
            "uq_passport_roster_resolutions_active_submission",
            "submission_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "uq_passport_roster_resolutions_active_recipient",
            "broadcast_recipient_id",
            unique=True,
            postgresql_where=text("status = 'active' AND broadcast_recipient_id IS NOT NULL"),
            sqlite_where=text("status = 'active' AND broadcast_recipient_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    broadcast_recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_recipients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    replaced_recipient_normalized_phone: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    original_recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_recipient_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_recipient_imported_fields: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    resolution_type: Mapped[str] = mapped_column(String(24), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    suppressed_recipient_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    excluded_submission_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    restored_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
