"""Document distribution, rename, upload, and cleanup SQLAlchemy models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class DocumentDistributionBatchModel(Base):
    __tablename__ = "document_distribution_batches"
    __table_args__ = (
        Index("ix_document_batches_group_type_created", "group_id", "document_type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    uploaded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class DistributedDocumentModel(Base):
    __tablename__ = "distributed_documents"
    __table_args__ = (
        Index("ix_distributed_documents_batch_passenger", "batch_id", "passenger_id"),
        Index("ix_distributed_documents_group_type", "group_id", "document_type"),
        Index(
            "ix_distributed_documents_mobile_passenger",
            "agency_id",
            "group_id",
            "passenger_id",
            "match_status",
            "document_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_distribution_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    passenger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    document_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(120), nullable=False, default="application/pdf"
    )
    detected_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    match_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="needs_review", index=True
    )
    match_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    match_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted_passport_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    extracted_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class DocumentWhatsAppDeliveryModel(Base):
    """Durable, idempotent WhatsApp delivery state for one passenger document."""

    __tablename__ = "document_whatsapp_deliveries"
    __table_args__ = (
        Index(
            "ix_document_whatsapp_delivery_group_status",
            "group_id",
            "status",
        ),
        Index(
            "ix_document_whatsapp_delivery_send_batch",
            "send_batch_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_distribution_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    distributed_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("distributed_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    passenger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    broadcast_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_recipients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    send_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    document_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    passenger_name: Mapped[str] = mapped_column(String(255), nullable=False)
    passport_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone_number: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_phone_number: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    template_name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_parameter_values: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    provider_media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    provider_status_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


class DocumentRenameBatchModel(Base):
    __tablename__ = "document_rename_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="Rename Batch")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed", index=True)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    visa_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ticket_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unknown_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class DocumentRenameItemModel(Base):
    __tablename__ = "document_rename_items"
    __table_args__ = (Index("ix_document_rename_items_batch_created", "batch_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_rename_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    renamed_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(120), nullable=False, default="application/pdf"
    )
    detected_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", index=True
    )
    extracted_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted_passport_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    extracted_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="renamed", index=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class DocumentUploadChunkModel(Base):
    """Durable idempotency receipt for one bounded document-upload chunk."""

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


class StorageCleanupJobModel(Base):
    """Encrypted tombstone retained until object-storage deletion succeeds."""

    __tablename__ = "storage_cleanup_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'blocked')",
            name="ck_storage_cleanup_jobs_status",
        ),
        CheckConstraint("object_count > 0", name="ck_storage_cleanup_jobs_object_count"),
        CheckConstraint("attempts >= 0", name="ck_storage_cleanup_jobs_attempts"),
        CheckConstraint(
            "encryption_key_version >= 1",
            name="ck_storage_cleanup_jobs_key_version",
        ),
        Index(
            "ix_storage_cleanup_jobs_due",
            "status",
            "next_attempt_at",
            "created_at",
        ),
        Index(
            "ix_storage_cleanup_jobs_expired_lease",
            "status",
            "lease_expires_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    context_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_keys_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_key_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    object_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
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
