"""Published immutable common documents for a group."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.gc_mobile_models import _utcnow
from app.infrastructure.database.model_base import Base


class GCCommonDocumentModel(Base):
    """One immutable version of a common, non-passenger-owned group document."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "gc_common_documents"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            name="uq_gc_common_doc_scope",
        ),
        UniqueConstraint("storage_key", name="uq_gc_common_doc_storage_key"),
        UniqueConstraint(
            "gc_group_access_id",
            "logical_document_id",
            "version",
            name="uq_gc_common_doc_logical_version",
        ),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_gc_common_doc_access",
            ondelete="CASCADE",
        ),
        CheckConstraint("version >= 1", name="ck_gc_common_doc_version"),
        CheckConstraint("byte_size > 0", name="ck_gc_common_doc_size"),
        CheckConstraint(
            "length(checksum_sha256) = 64",
            name="ck_gc_common_doc_checksum",
        ),
        CheckConstraint(
            "category IN ('itinerary_pdf', 'travel_tips', 'common_instructions', "
            "'destination', 'emergency', 'hotel', 'flight_summary', 'meeting_point', "
            "'dress_code', 'baggage', 'other')",
            name="ck_gc_common_doc_category",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'retired', 'revoked')",
            name="ck_gc_common_doc_status",
        ),
        CheckConstraint(
            "availability_expires_at IS NULL OR availability_starts_at IS NULL "
            "OR availability_expires_at > availability_starts_at",
            name="ck_gc_common_doc_window",
        ),
        CheckConstraint(
            "(status = 'draft' AND published_at IS NULL) OR "
            "(status IN ('published', 'retired', 'revoked') AND published_at IS NOT NULL)",
            name="ck_gc_common_doc_publish_shape",
        ),
        CheckConstraint(
            "status != 'published' OR "
            "(passenger_visible OR client_manager_visible OR coordinator_visible)",
            name="ck_gc_common_doc_audience",
        ),
        Index(
            "uq_gc_common_doc_published",
            "gc_group_access_id",
            "logical_document_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
            sqlite_where=text("status = 'published'"),
        ),
        Index(
            "ix_gc_common_doc_manifest",
            "gc_group_access_id",
            "status",
            "sort_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    logical_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    passenger_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    client_manager_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    coordinator_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    offline_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    availability_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    availability_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
