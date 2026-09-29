"""Agency-scoped immutable contact sources, never attached to an invented trip."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class MCPContactImportUploadModel(Base):
    __tablename__ = "mcp_contact_import_uploads"
    __table_args__ = (
        CheckConstraint("byte_size BETWEEN 1 AND 5242880", name="ck_mcp_contact_upload_size"),
        CheckConstraint("expires_at > created_at", name="ck_mcp_contact_upload_expiry"),
        CheckConstraint(
            "(consumed_operation_id IS NULL AND consumed_at IS NULL) OR "
            "(consumed_operation_id IS NOT NULL AND consumed_at IS NOT NULL)",
            name="ck_mcp_contact_upload_consumed",
        ),
        Index("ix_mcp_contact_upload_expiry", "expires_at"),
        Index("ix_mcp_contact_upload_grant_created", "original_grant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    original_grant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mcp_grants.id", ondelete="SET NULL")
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"))
    handle_hash: Mapped[str] = mapped_column(String(64), unique=True)
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    filename: Mapped[str] = mapped_column(String(120))
    media_type: Mapped[str] = mapped_column(String(120))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    workbook_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_operation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mcp_operations.id", ondelete="RESTRICT"), unique=True
    )
    broadcast_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="SET NULL")
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
