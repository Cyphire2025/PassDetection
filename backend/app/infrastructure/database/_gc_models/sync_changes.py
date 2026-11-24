"""Durable ordered mutation journal entries for trip synchronization."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
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


class MobileSyncChangeModel(Base):
    """Monotonic compact change feed; file bodies and secrets are never embedded."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "mobile_sync_changes"
    __table_args__ = (
        UniqueConstraint("id", name="uq_mobile_sync_change_id"),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_sync_change_access",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["passenger_identity_id", "gc_group_access_id", "agency_id", "group_id"],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
            ],
            name="fk_mobile_sync_change_passenger",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "audience IN ('all', 'passenger', 'client_manager', 'coordinator')",
            name="ck_mobile_sync_change_audience",
        ),
        CheckConstraint(
            "operation IN ('upsert', 'delete', 'revoke', 'publish')",
            name="ck_mobile_sync_change_operation",
        ),
        CheckConstraint("version >= 1", name="ck_mobile_sync_change_version"),
        CheckConstraint(
            "access_generation >= 0",
            name="ck_mobile_sync_change_generation",
        ),
        CheckConstraint(
            "payload_checksum IS NULL OR length(payload_checksum) = 64",
            name="ck_mobile_sync_change_checksum",
        ),
        CheckConstraint(
            "passenger_identity_id IS NULL OR audience = 'passenger'",
            name="ck_mobile_sync_change_passenger_audience",
        ),
        Index("ix_mobile_sync_change_agency_cursor", "agency_id", "sequence"),
        Index("ix_mobile_sync_change_group_cursor", "gc_group_access_id", "sequence"),
        Index(
            "ix_mobile_sync_change_passenger_cursor",
            "passenger_identity_id",
            "sequence",
        ),
        Index("ix_mobile_sync_change_expiry", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    sequence: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(always=False),
        primary_key=True,
        autoincrement=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passenger_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    audience: Mapped[str] = mapped_column(
        String(24), nullable=False, default="all", server_default="all"
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    access_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    payload_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
