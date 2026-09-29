"""Private, connection-bound temporary transfers; source records are never removed."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class MCPArtifactModel(Base):
    __tablename__ = "mcp_artifacts"
    __table_args__ = (
        CheckConstraint("direction IN ('upload', 'export')", name="ck_mcp_artifact_direction"),
        CheckConstraint("byte_size > 0", name="ck_mcp_artifact_size"),
        CheckConstraint("expires_at > created_at", name="ck_mcp_artifact_expiry"),
        CheckConstraint(
            "delivered_at IS NULL OR (direction = 'export' AND download_completed_at IS NOT NULL)",
            name="ck_mcp_artifact_delivery",
        ),
        CheckConstraint(
            "export_history_id IS NULL OR direction = 'export'", name="ck_mcp_artifact_history"
        ),
        CheckConstraint(
            "(export_history_id IS NULL AND export_checkpoint_sha256 IS NULL) OR "
            "(export_history_id IS NOT NULL AND export_checkpoint_sha256 IS NOT NULL)",
            name="ck_mcp_artifact_checkpoint",
        ),
        Index("ix_mcp_artifacts_expiry", "expires_at"),
        Index("ix_mcp_artifacts_grant_created", "grant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    handle_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    grant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mcp_grants.id", ondelete="RESTRICT"))
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"))
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("client_groups.id", ondelete="CASCADE"))
    association_groups: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    direction: Mapped[str] = mapped_column(String(8))
    purpose: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    filename: Mapped[str] = mapped_column(String(120))
    media_type: Mapped[str] = mapped_column(String(120))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    download_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    export_history_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("passport_export_history.id", ondelete="CASCADE"), unique=True
    )
    export_checkpoint_sha256: Mapped[str | None] = mapped_column(String(64))
    ingestion_operation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mcp_operations.id", ondelete="RESTRICT"), unique=True
    )


class MCPArtifactAccessModel(Base):
    """A locator authorizes one grant; original artifact provenance stays immutable."""

    __tablename__ = "mcp_artifact_access"
    __table_args__ = (
        CheckConstraint("handle_version IN (0, 1)", name="ck_mcp_artifact_access_version"),
    )

    artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mcp_artifacts.id", ondelete="CASCADE"), primary_key=True
    )
    grant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mcp_grants.id", ondelete="RESTRICT"), primary_key=True
    )
    handle_hash: Mapped[str] = mapped_column(String(64), unique=True)
    handle_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
