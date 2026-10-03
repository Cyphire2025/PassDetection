"""Limited native handoff tickets; no plaintext transfer credential is retained."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
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

from app.infrastructure.database.model_base import Base, _utcnow


class MCPNativeTransferModel(Base):
    __tablename__ = "mcp_native_transfers"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('upload_workbook','upload_pdf','download')",
            name="ck_mcp_native_transfer_kind",
        ),
        CheckConstraint(
            "purpose IN ('contact_broadcast','group_workbook','document_pdf','export')",
            name="ck_mcp_native_transfer_purpose",
        ),
        CheckConstraint(
            "status IN ('pending','transferring','completed','failed')",
            name="ck_mcp_native_transfer_status",
        ),
        CheckConstraint("byte_size > 0", name="ck_mcp_native_transfer_size"),
        CheckConstraint("security_version >= 1", name="ck_mcp_native_transfer_security"),
        CheckConstraint("expires_at > created_at", name="ck_mcp_native_transfer_expiry"),
        CheckConstraint(
            "(kind='upload_workbook' AND purpose IN ('contact_broadcast','group_workbook')) OR (kind='upload_pdf' AND purpose='document_pdf') OR (kind='download' AND purpose='export')",
            name="ck_mcp_native_transfer_lane",
        ),
        UniqueConstraint(
            "original_grant_id", "kind", "idempotency_hash", name="uq_mcp_native_transfer_retry"
        ),
        Index("ix_mcp_native_transfer_grant_created", "original_grant_id", "created_at"),
        Index("ix_mcp_native_transfer_expiry", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_grant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mcp_grants.id", ondelete="RESTRICT")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    security_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    purpose: Mapped[str] = mapped_column(String(24))
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    filename: Mapped[str] = mapped_column(String(120))
    media_type: Mapped[str] = mapped_column(String(120))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    idempotency_hash: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claim_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    workbook_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mcp_contact_import_uploads.id", ondelete="SET NULL"), nullable=True
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mcp_artifacts.id", ondelete="SET NULL"), nullable=True
    )
    download_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
