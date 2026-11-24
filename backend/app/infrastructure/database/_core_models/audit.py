"""Per-scope audit chain heads and immutable audit event records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class AuditChainHeadModel(Base):
    """Serialized per-scope head for the application audit hash chain."""
    __module__ = "app.infrastructure.database.models"

    __tablename__ = "audit_chain_heads"
    __table_args__ = (
        CheckConstraint(
            "integrity_version = 1",
            name="ck_audit_chain_head_version",
        ),
        CheckConstraint(
            "last_sequence >= 0",
            name="ck_audit_chain_head_sequence",
        ),
        CheckConstraint(
            "length(last_hash) = 64",
            name="ck_audit_chain_head_hash",
        ),
    )

    scope_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    agency_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    integrity_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    last_sequence: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    last_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="0" * 64,
        server_default="0" * 64,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


class AuditLogModel(Base):
    __module__ = "app.infrastructure.database.models"
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "result IN ('success', 'blocked', 'denied', 'failed')",
            name="ck_audit_logs_result",
        ),
        CheckConstraint(
            "(integrity_version = 0 AND integrity_scope IS NULL "
            "AND integrity_sequence IS NULL AND previous_hash IS NULL AND entry_hash IS NULL) "
            "OR (integrity_version = 1 AND integrity_scope IS NOT NULL "
            "AND integrity_sequence > 0 AND length(previous_hash) = 64 "
            "AND length(entry_hash) = 64)",
            name="ck_audit_logs_integrity_shape",
        ),
        Index(
            "uq_audit_logs_integrity_sequence",
            "integrity_scope",
            "integrity_sequence",
            unique=True,
            postgresql_where=text("integrity_version = 1"),
            sqlite_where=text("integrity_version = 1"),
        ),
        Index(
            "ix_audit_logs_scope_created_id",
            "agency_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_audit_logs_filter_entity_result",
            "agency_id",
            "entity_type",
            "result",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )
    result: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="success",
        server_default="success",
    )
    integrity_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    integrity_scope: Mapped[str | None] = mapped_column(String(80), nullable=True)
    integrity_sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
