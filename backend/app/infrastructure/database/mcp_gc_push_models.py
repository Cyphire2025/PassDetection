"""Reviewed GC push plans and retained per-notification MCP origin markers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, column, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


def _hash_alphabet() -> ColumnElement[bool]:
    remaining: ColumnElement[str] = column("snapshot_hash")
    for character in "0123456789abcdef":
        remaining = func.replace(remaining, character, "")
    return remaining == ""


class MCPGCPushPlanModel(Base):
    __tablename__ = "mcp_gc_push_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('prepared','queued','blocked','completed')",
            name="ck_mcp_gc_push_plan_status",
        ),
        CheckConstraint("revision >= 1", name="ck_mcp_gc_push_plan_revision"),
        CheckConstraint("length(snapshot_hash) = 64", name="ck_mcp_gc_push_plan_hash_length"),
        CheckConstraint(_hash_alphabet(), name="ck_mcp_gc_push_plan_hash_alphabet"),
        CheckConstraint("expires_at > prepared_at", name="ck_mcp_gc_push_plan_expiry"),
        Index("ix_mcp_gc_push_plans_user_prepared", "user_id", "prepared_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mcp_operations.id", ondelete="CASCADE"), unique=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    original_grant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mcp_grants.id", ondelete="SET NULL"), nullable=True
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"))
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gc_notification_drafts.id", ondelete="SET NULL"), nullable=True
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="prepared")
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=True
    )


class MCPGCPushOriginModel(Base):
    """A removed plan leaves a marker, so its outbox cannot become an ordinary send."""

    __tablename__ = "mcp_gc_push_origins"
    __table_args__ = (
        Index("ix_mcp_gc_push_origins_plan", "plan_id", "notification_id"),
        Index("ix_mcp_gc_push_origins_batch", "batch_id"),
    )
    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mobile_notifications.id", ondelete="CASCADE"), primary_key=True
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gc_notification_batches.id", ondelete="CASCADE")
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mcp_gc_push_plans.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
