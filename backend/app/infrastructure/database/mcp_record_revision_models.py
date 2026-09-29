"""Before/after history for reviewed MCP passport contact/detail corrections."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class MCPRecordRevisionModel(Base):
    __tablename__ = "mcp_record_revisions"
    __table_args__ = (
        CheckConstraint(
            "entity_type = 'passport_submission'", name="ck_mcp_record_revision_entity"
        ),
        UniqueConstraint(
            "operation_id",
            "entity_type",
            "entity_id",
            name="uq_mcp_record_revision_operation_entity",
        ),
        Index("ix_mcp_record_revisions_entity_created", "entity_id", "created_at"),
        Index(
            "ix_mcp_record_revisions_agency_group_created", "agency_id", "group_id", "created_at"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mcp_operations.id", ondelete="CASCADE")
    )
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("passport_submissions.id", ondelete="CASCADE")
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"))
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("client_groups.id", ondelete="CASCADE"))
    before_values: Mapped[dict[str, Any]] = mapped_column(JSONB)
    after_values: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
