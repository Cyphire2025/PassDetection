"""Bounded idempotency receipts for chunked document uploads."""

from __future__ import annotations

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

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class DocumentUploadChunkModel(Base):
    """Durable idempotency receipt for one bounded document-upload chunk."""

    __module__ = "app.infrastructure.database.document_models"

    __tablename__ = "document_upload_chunks"
    __table_args__ = (
        UniqueConstraint(
            "workflow",
            "upload_id",
            "chunk_index",
            name="uq_document_upload_chunks_workflow_upload_index",
        ),
        CheckConstraint("chunk_index >= 0", name="ck_document_upload_chunks_index"),
        CheckConstraint(
            "chunk_index < expected_chunk_count",
            name="ck_document_upload_chunks_index_manifest",
        ),
        CheckConstraint(
            "expected_chunk_count BETWEEN 1 AND 1500",
            name="ck_document_upload_chunks_expected_chunks",
        ),
        CheckConstraint(
            "expected_file_count BETWEEN 1 AND 1500",
            name="ck_document_upload_chunks_expected_files",
        ),
        CheckConstraint(
            "expected_file_count >= expected_chunk_count "
            "AND expected_file_count <= expected_chunk_count * 50",
            name="ck_document_upload_chunks_manifest_capacity",
        ),
        CheckConstraint(
            "file_count BETWEEN 1 AND 50",
            name="ck_document_upload_chunks_file_count",
        ),
        CheckConstraint(
            "byte_count BETWEEN 1 AND 67108864",
            name="ck_document_upload_chunks_byte_count",
        ),
        CheckConstraint(
            "accepted_count >= 0 AND rejected_count >= 0 "
            "AND accepted_count + rejected_count = file_count",
            name="ck_document_upload_chunks_result_counts",
        ),
        CheckConstraint(
            "workflow IN ('rename', 'distribution')",
            name="ck_document_upload_chunks_workflow",
        ),
        CheckConstraint(
            "(workflow = 'rename' AND group_id IS NULL AND document_type IS NULL) "
            "OR (workflow = 'distribution' AND group_id IS NOT NULL "
            "AND document_type IN "
            "('visa', 'flight_ticket', 'flight_ticket_arrival', "
            "'flight_ticket_domestic', 'flight_ticket_domestic_arrival', 'other'))",
            name="ck_document_upload_chunks_scope",
        ),
        Index(
            "ix_document_upload_chunks_scope",
            "agency_id",
            "workflow",
            "upload_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    upload_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow: Mapped[str] = mapped_column(String(32), nullable=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=True,
    )
    document_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_file_count: Mapped[int] = mapped_column(Integer, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_documents: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
