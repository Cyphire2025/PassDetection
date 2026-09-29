"""Website send idempotency and broker outbox; retained original queued receipt."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

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


class WhatsAppSendIntentModel(Base):
    __tablename__ = "whatsapp_send_intents"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_hash", name="uq_whatsapp_send_intent_actor_key"),
        CheckConstraint(
            "publication_status IN ('no_batch','pending','published','completed','blocked')",
            name="ck_whatsapp_send_intent_publication_status",
        ),
        CheckConstraint("publication_attempts >= 0", name="ck_whatsapp_send_intent_attempts"),
        Index("ix_whatsapp_send_intents_due", "publication_status", "next_attempt_at"),
        Index("ix_whatsapp_send_intents_actor_created", "user_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"))
    broadcast_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE")
    )
    idempotency_hash: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    initial_response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    worker_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, unique=True
    )
    publication_status: Mapped[str] = mapped_column(String(16), default="no_batch")
    publication_attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
