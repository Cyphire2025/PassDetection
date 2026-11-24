"""Versioned group announcement publication and audience metadata."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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


class GCAnnouncementModel(Base):
    """A versioned, role-targeted group update safe for offline display."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "gc_announcements"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            name="uq_gc_announcement_scope",
        ),
        UniqueConstraint(
            "gc_group_access_id",
            "logical_announcement_id",
            "version",
            name="uq_gc_announcement_logical_version",
        ),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_gc_announcement_access",
            ondelete="CASCADE",
        ),
        CheckConstraint("version >= 1", name="ck_gc_announcement_version"),
        CheckConstraint(
            "category IN ('general', 'itinerary', 'room', 'flight', 'document', "
            "'coordinator', 'emergency', 'sync')",
            name="ck_gc_announcement_category",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'emergency')",
            name="ck_gc_announcement_priority",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'retired', 'revoked')",
            name="ck_gc_announcement_status",
        ),
        CheckConstraint(
            "availability_expires_at IS NULL OR availability_starts_at IS NULL "
            "OR availability_expires_at > availability_starts_at",
            name="ck_gc_announcement_window",
        ),
        CheckConstraint(
            "(status = 'draft' AND published_at IS NULL) OR "
            "(status IN ('published', 'retired', 'revoked') AND published_at IS NOT NULL)",
            name="ck_gc_announcement_publish_shape",
        ),
        CheckConstraint(
            "status != 'published' OR "
            "(passenger_visible OR client_manager_visible OR coordinator_visible)",
            name="ck_gc_announcement_audience",
        ),
        Index(
            "uq_gc_announcement_published",
            "gc_group_access_id",
            "logical_announcement_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
            sqlite_where=text("status = 'published'"),
        ),
        Index(
            "ix_gc_announcement_feed",
            "gc_group_access_id",
            "status",
            "published_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    logical_announcement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(
        String(24), nullable=False, default="general", server_default="general"
    )
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", server_default="normal"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    deep_link_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
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
