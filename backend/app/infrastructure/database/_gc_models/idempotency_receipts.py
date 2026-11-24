"""Stored request receipts for idempotent mobile mutations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.gc_mobile_models import _utcnow
from app.infrastructure.database.model_base import JSONB, Base


class MobileIdempotencyReceiptModel(Base):
    """Durable result of one offline mutation, keyed within a device session."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "mobile_idempotency_receipts"
    __table_args__ = (
        UniqueConstraint("session_id", "idempotency_key", name="uq_mobile_idempotency_session_key"),
        ForeignKeyConstraint(
            ["session_id", "agency_id"],
            ["mobile_device_sessions.id", "mobile_device_sessions.agency_id"],
            name="fk_mobile_idempotency_session",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_idempotency_access",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed', 'conflict')",
            name="ck_mobile_idempotency_status",
        ),
        CheckConstraint(
            "length(request_hash) = 64",
            name="ck_mobile_idempotency_request_hash",
        ),
        CheckConstraint(
            "response_hash IS NULL OR length(response_hash) = 64",
            name="ck_mobile_idempotency_response_hash",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_mobile_idempotency_expiry",
        ),
        CheckConstraint(
            "(gc_group_access_id IS NULL) = (group_id IS NULL)",
            name="ck_mobile_idempotency_group_pair",
        ),
        CheckConstraint(
            "(status = 'processing' AND completed_at IS NULL) OR "
            "(status != 'processing' AND completed_at IS NOT NULL)",
            name="ck_mobile_idempotency_completion",
        ),
        Index("ix_mobile_idempotency_expiry", "expires_at"),
        Index("ix_mobile_idempotency_status", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    gc_group_access_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="processing", server_default="processing"
    )
    response_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
