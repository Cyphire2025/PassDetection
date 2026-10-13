"""Durable company export checkpoints and immutable bounded output volumes."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base
from app.infrastructure.database.traveller_model_support import (
    TravellerRecord,
    company_scope,
    record_scope,
)


class CompanyDataExportJobModel(TravellerRecord, Base):
    __tablename__ = "company_data_export_jobs"
    __table_args__ = (
        company_scope("company_data_export"), record_scope("company_data_export"),
        UniqueConstraint("agency_id", "company_id", "requested_by_user_id", "idempotency_key", name="uq_company_export_request"),
        CheckConstraint("kind IN ('excel','images')", name="ck_company_export_kind"),
        CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled','expired')", name="ck_company_export_status"),
        CheckConstraint("processed_count >= 0 AND part_count >= 0 AND attempt_count >= 0", name="ck_company_export_counts"),
        CheckConstraint("company_revision >= 1", name="ck_company_export_company_revision"),
        CheckConstraint("phase IN ('people','retained_images','source_front','source_back','source_cover','source_back_cover','source_photo','finalize')", name="ck_company_export_phase"),
        Index("ix_company_export_live_lease", "lease_expires_at",
            postgresql_where=text("lease_expires_at IS NOT NULL"), sqlite_where=text("lease_expires_at IS NOT NULL")),
        Index("ix_company_export_pending_scope", "agency_id", "company_id", "id",
            postgresql_where=text("status IN ('queued','running')"), sqlite_where=text("status IN ('queued','running')")),
        Index("ix_company_export_cleanup", "expires_at", "id",
            postgresql_where=text("status != 'expired'"), sqlite_where=text("status != 'expired'")),
        Index("ix_company_export_queue", "status", "available_at", "id"),
        Index("ix_company_export_scope", "agency_id", "company_id", "requested_by_user_id", "created_at", "id"),
        Index("ix_company_export_expiry", "expires_at", "status", "id"),
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", server_default="queued")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    company_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(24), nullable=False, default="people", server_default="people")
    cursor: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    part_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CompanyDataExportPartModel(TravellerRecord, Base):
    __tablename__ = "company_data_export_parts"
    __table_args__ = (
        ForeignKeyConstraint(["job_id", "agency_id", "company_id"],
            ["company_data_export_jobs.id", "company_data_export_jobs.agency_id", "company_data_export_jobs.company_id"],
            name="fk_company_export_part_job", ondelete="RESTRICT"),
        UniqueConstraint("job_id", "part_number", name="uq_company_export_part_number"),
        CheckConstraint("part_number >= 1 AND byte_size > 0 AND record_count >= 0", name="ck_company_export_part_shape"),
        CheckConstraint("part_kind IN ('rows','images','workbook')", name="ck_company_export_part_kind"),
        Index("ix_company_export_part_unpurged", "job_id", "id",
            postgresql_where=text("purged_at IS NULL"), sqlite_where=text("purged_at IS NULL")),
        Index("ix_company_export_part_scope", "agency_id", "company_id", "job_id", "part_number"),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    part_number: Mapped[int] = mapped_column(Integer, nullable=False)
    part_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
