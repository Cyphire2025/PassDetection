"""Versioned passport evidence, privately owned assets and frozen trip references."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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

from app.infrastructure.database.model_base import JSONB, Base
from app.infrastructure.database.traveller_model_support import (
    TravellerRecord,
    company_scope,
    document_scope,
    group_scope,
    passport_scope,
    record_scope,
    traveller_scope,
)


class TravellerPassportModel(TravellerRecord, Base):
    __tablename__ = "traveller_passports"
    __table_args__ = (
        traveller_scope("traveller_passport"),
        record_scope("traveller_passport"),
        UniqueConstraint(
            "id", "traveller_id", "agency_id", "company_id", name="uq_traveller_passport_owner"
        ),
        CheckConstraint(
            "status IN ('candidate','accepted','superseded','lost','cancelled','compromised','rejected','disputed')",
            name="ck_traveller_passport_status",
        ),
        CheckConstraint("revision >= 1", name="ck_traveller_passport_revision"),
        CheckConstraint("length(issuing_country) IN (2,3)", name="ck_traveller_passport_issuer"),
        CheckConstraint(
            "is_default = false OR status = 'accepted'",
            name="ck_traveller_passport_default_accepted",
        ),
        Index(
            "ix_traveller_passport_match",
            "agency_id",
            "company_id",
            "fingerprint_key_version",
            "issuing_country",
            "document_type",
            "number_fingerprint",
        ),
        Index("ix_traveller_passport_owner", "agency_id", "company_id", "traveller_id", "status"),
        Index("ix_traveller_passport_fingerprint", "agency_id", "company_id", "fingerprint_key_version", "number_fingerprint"),
        Index("ix_traveller_passport_number_lookup", "agency_id", "company_id", "fingerprint_key_version", "number_lookup_fingerprint"),
        Index(
            "uq_traveller_passport_default",
            "traveller_id",
            unique=True,
            postgresql_where=text("is_default = true"),
            sqlite_where=text("is_default = true"),
        ),
    )
    traveller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    issuing_country: Mapped[str] = mapped_column(String(3), nullable=False)
    issuing_authority: Mapped[str | None] = mapped_column(String(128), nullable=True)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    number_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    number_lookup_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fingerprint_key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    number_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="candidate", server_default="candidate"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class TravellerDocumentRevisionModel(TravellerRecord, Base):
    __tablename__ = "traveller_document_revisions"
    __table_args__ = (
        passport_scope("traveller_document_revision"),
        record_scope("traveller_document_revision"),
        UniqueConstraint(
            "id",
            "passport_id",
            "traveller_id",
            "agency_id",
            "company_id",
            name="uq_traveller_document_owner",
        ),
        UniqueConstraint("passport_id", "revision_number", name="uq_traveller_document_revision"),
        UniqueConstraint(
            "agency_id", "company_id", "idempotency_key", name="uq_traveller_document_idempotency"
        ),
        ForeignKeyConstraint(
            ["source_submission_id", "agency_id", "source_group_id"],
            ["passport_submissions.id", "passport_submissions.agency_id", "passport_submissions.group_id"],
            name="fk_traveller_document_source_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("revision_number >= 1", name="ck_traveller_document_revision_number"),
        CheckConstraint(
            "(source_submission_id IS NULL AND source_group_id IS NULL) OR "
            "(source_submission_id IS NOT NULL AND source_group_id IS NOT NULL)",
            name="ck_traveller_document_source_shape",
        ),
        CheckConstraint(
            "status IN ('candidate','accepted','rejected')", name="ck_traveller_document_status"
        ),
        CheckConstraint(
            "status != 'accepted' OR accepted_at IS NOT NULL",
            name="ck_traveller_document_accepted_evidence",
        ),
        CheckConstraint(
            "expiry_date IS NULL OR issue_date IS NULL OR expiry_date >= issue_date",
            name="ck_traveller_document_dates",
        ),
        Index("ix_traveller_document_latest", "passport_id", "status", "revision_number"),
        Index("ix_traveller_document_source", "source_submission_id", "id"),
        Index("ix_traveller_document_person_seek", "agency_id", "company_id", "traveller_id", "created_at", "id"),
    )
    passport_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    traveller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="candidate", server_default="candidate"
    )
    fields_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    source_provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    reliable_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_submission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    source_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)


class TravellerDocumentAssetModel(TravellerRecord, Base):
    __tablename__ = "traveller_document_assets"
    __table_args__ = (
        document_scope("traveller_document_asset"),
        record_scope("traveller_document_asset"),
        CheckConstraint("kind IN ('original','derivative')", name="ck_traveller_asset_kind"),
        CheckConstraint(
            "availability IN ('pending','available','unreadable','purged')",
            name="ck_traveller_asset_availability",
        ),
        CheckConstraint("byte_size >= 0", name="ck_traveller_asset_size"),
        CheckConstraint("copy_attempt_count >= 0", name="ck_traveller_asset_copy_attempts"),
        CheckConstraint(
            "availability != 'available' OR (object_key IS NOT NULL AND retention_basis IS NOT NULL)",
            name="ck_traveller_asset_retained",
        ),
        UniqueConstraint("agency_id", "object_key", name="uq_traveller_asset_object"),
        Index(
            "ix_traveller_asset_document",
            "agency_id",
            "company_id",
            "document_revision_id",
            "availability",
        ),
        Index("ix_traveller_asset_retention", "retention_until", "availability", "id"),
        Index("ix_traveller_asset_copy_queue", "availability", "next_attempt_at", "id"),
        Index("ix_traveller_asset_copy_lease", "lease_expires_at"),
        Index("ix_traveller_asset_owner_state", "traveller_id", "availability", "id"),
        Index("ix_traveller_asset_object", "object_key"),
        Index("ix_traveller_asset_company_seek", "agency_id", "company_id", "id"),
    )
    document_revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passport_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    traveller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    document_side: Mapped[str] = mapped_column(String(32), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_extraction_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    copy_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    availability: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_basis: Mapped[str | None] = mapped_column(String(128), nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TravellerParticipationModel(TravellerRecord, Base):
    __tablename__ = "traveller_participations"
    __table_args__ = (
        traveller_scope("traveller_participation"),
        group_scope("traveller_participation"),
        document_scope("traveller_participation"),
        record_scope("traveller_participation"),
        UniqueConstraint("group_id", "traveller_id", name="uq_traveller_participation_membership"),
        UniqueConstraint(
            "agency_id",
            "company_id",
            "group_id",
            "idempotency_key",
            name="uq_traveller_participation_idempotency",
        ),
        UniqueConstraint(
            "agency_id",
            "company_id",
            "group_id",
            "source_kind",
            "source_row_key",
            name="uq_traveller_participation_source",
        ),
        ForeignKeyConstraint(
            ["source_submission_id", "agency_id", "group_id"],
            [
                "passport_submissions.id",
                "passport_submissions.agency_id",
                "passport_submissions.group_id",
            ],
            name="fk_traveller_participation_source_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('pending','submitted','accepted','withdrawn')",
            name="ck_traveller_participation_status",
        ),
        CheckConstraint(
            "revision >= 1 AND profile_revision >= 1 AND contact_revision >= 1",
            name="ck_traveller_participation_revisions",
        ),
        CheckConstraint(
            "(document_revision_id IS NULL AND passport_id IS NULL) OR (document_revision_id IS NOT NULL AND passport_id IS NOT NULL)",
            name="ck_traveller_participation_document_shape",
        ),
        Index(
            "ix_traveller_participation_groups",
            "agency_id",
            "company_id",
            "group_id",
            "status",
            "id",
        ),
        Index(
            "ix_traveller_participation_history",
            "agency_id",
            "company_id",
            "traveller_id",
            "trip_started_at",
            "id",
        ),
        Index("ix_traveller_participation_document", "document_revision_id", "status", "id"),
        Index("ix_traveller_participation_submission", "source_submission_id"),
        Index("ix_traveller_participation_person_seek", "agency_id", "company_id", "traveller_id", "id"),
    )
    traveller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_submission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_row_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    passport_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    document_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    contact_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    question_version: Mapped[str] = mapped_column(String(128), nullable=False)
    confirmations: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trip_started_at: Mapped[date | None] = mapped_column(Date, nullable=True)


class TravellerGroupReuseConfigModel(Base):
    __tablename__ = "traveller_group_reuse_configs"
    __table_args__ = (
        company_scope("traveller_group_reuse_config"),
        group_scope("traveller_group_reuse_config"),
        CheckConstraint("roster_mode IN ('closed','open')", name="ck_traveller_group_roster_mode"),
        CheckConstraint("revision >= 1", name="ck_traveller_group_config_revision"),
        CheckConstraint(
            "identifier_required = false OR individual_identifier_type IS NOT NULL",
            name="ck_traveller_group_identifier_config",
        ),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    roster_mode: Mapped[str] = mapped_column(
        String(8), nullable=False, default="closed", server_default="closed"
    )
    individual_identifier_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    identifier_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
