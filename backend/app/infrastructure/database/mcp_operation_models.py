"""MCP transaction receipts and durable workflow observations, separate from grants."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class MCPOperationModel(Base):
    __tablename__ = "mcp_operations"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "operation_name", "idempotency_hash", name="uq_mcp_operation_user_name_key"
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'unknown')",
            name="ck_mcp_operation_status",
        ),
        CheckConstraint("progress >= 0 AND progress <= 1", name="ck_mcp_operation_progress"),
        CheckConstraint("revision >= 0", name="ck_mcp_operation_revision"),
        CheckConstraint(
            "status != 'succeeded' OR progress = 1", name="ck_mcp_operation_success_progress"
        ),
        Index("ix_mcp_operations_user_created", "user_id", "created_at"),
        Index("ix_mcp_operations_workflow", "workflow_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    initial_grant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mcp_grants.id", ondelete="RESTRICT")
    )
    operation_name: Mapped[str] = mapped_column(String(120))
    capability: Mapped[str] = mapped_column(String(32))
    idempotency_hash: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    # Null exists only inside the claiming transaction, before its callback completes.
    initial_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16))
    progress: Mapped[float] = mapped_column(Float)
    stage: Mapped[str] = mapped_column(String(120))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_entities: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
