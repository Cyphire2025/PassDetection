"""Immutable two-phase group export checkpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class PassportExportHistoryModel(Base):
    """Two-phase, immutable checkpoint for one group export."""
    __module__ = "app.infrastructure.database.models"

    __tablename__ = "passport_export_history"
    __table_args__ = (
        UniqueConstraint(
            "group_id",
            "export_kind",
            "request_id",
            name="uq_passport_export_history_group_kind_request",
        ),
        CheckConstraint(
            "export_kind IN ('passport_images', 'passport_excel')",
            name="ck_passport_export_history_kind",
        ),
        CheckConstraint(
            "export_mode IN ('all', 'incremental')",
            name="ck_passport_export_history_mode",
        ),
        CheckConstraint(
            "total_available_count >= 0 AND exported_count >= 0 AND pending_recipient_count >= 0",
            name="ck_passport_export_history_counts",
        ),
        CheckConstraint(
            "format_version >= 1",
            name="ck_passport_export_history_format_version",
        ),
        CheckConstraint(
            "(status = 'prepared' AND completed_at IS NULL) "
            "OR (status = 'completed' AND completed_at IS NOT NULL)",
            name="ck_passport_export_history_completion",
        ),
        Index(
            "ix_passport_export_history_group_kind_created",
            "group_id",
            "export_kind",
            "created_at",
        ),
        Index(
            "ix_passport_export_history_group_kind_status_completed",
            "group_id",
            "export_kind",
            "status",
            "completed_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    export_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    export_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    format_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    baseline_export_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_export_history.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The cumulative checkpoint is deliberately separate from the file payload.
    # An incremental file may contain 19 people while its checkpoint represents
    # all 189 people available when that file was prepared.
    snapshot_submission_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    exported_submission_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    exported_people_snapshot: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    total_available_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    exported_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    pending_recipient_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    artifact_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="prepared", server_default="prepared"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
