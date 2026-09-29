"""Immutable reviewed WhatsApp intent and durable broker-publication state."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class MCPWhatsAppPlanModel(Base):
    __tablename__ = "mcp_whatsapp_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('prepared','queued','cancelled','blocked','completed')",
            name="ck_mcp_whatsapp_plan_status",
        ),
        CheckConstraint("revision >= 1", name="ck_mcp_whatsapp_plan_revision"),
        CheckConstraint("expires_at > prepared_at", name="ck_mcp_whatsapp_plan_expiry"),
        Index("ix_mcp_whatsapp_plans_user_prepared", "user_id", "prepared_at"),
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
    broadcast_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE")
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="prepared")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, unique=True
    )


class MCPWhatsAppOutboxModel(Base):
    __tablename__ = "mcp_whatsapp_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','published','completed','cancelled','blocked')",
            name="ck_mcp_whatsapp_outbox_status",
        ),
        CheckConstraint("publication_attempts >= 0", name="ck_mcp_whatsapp_outbox_attempts"),
        Index("ix_mcp_whatsapp_outbox_due", "status", "next_attempt_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mcp_whatsapp_plans.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    publication_attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
