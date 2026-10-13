"""Stable identities, contact history and explicit future-reuse authority.

Fingerprints are keyed, domain-separated HMACs produced by the application.
They are intentionally not globally unique: ambiguous matches must be resolved,
and a shared phone never becomes a unique person key. Ciphertexts include their
encryption key version. Dates in immutable document revisions are not indexed.
"""

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
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base
from app.infrastructure.database.traveller_model_support import (
    TravellerRecord,
    company_scope,
    record_scope,
    traveller_scope,
)


class TravellerReusePolicyModel(Base):
    __tablename__ = "traveller_reuse_policies"
    __table_args__ = (
        company_scope("traveller_reuse_policy"),
        CheckConstraint("revision >= 1", name="ck_traveller_reuse_policy_revision"),
        CheckConstraint(
            "retention_days IS NULL OR retention_days BETWEEN 1 AND 3650",
            name="ck_traveller_reuse_policy_retention",
        ),
        CheckConstraint(
            "retention_mode IN ('until_withdrawn','limited')",
            name="ck_traveller_reuse_policy_retention_mode",
        ),
        CheckConstraint(
            "enabled = false OR ((retention_mode = 'until_withdrawn' OR retention_days IS NOT NULL) AND "
            "purpose_version IS NOT NULL AND length(trim(purpose_version)) > 0 AND "
            "notice_version IS NOT NULL AND length(trim(notice_version)) > 0 AND "
            "processing_basis IS NOT NULL AND length(trim(processing_basis)) > 0 AND "
            "configured_at IS NOT NULL)",
            name="ck_traveller_reuse_policy_activation",
        ),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_mode: Mapped[str] = mapped_column(
        String(24), nullable=False, default="until_withdrawn", server_default="until_withdrawn"
    )
    purpose_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notice_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    processing_basis: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    configured_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    configured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TravellerProfileModel(TravellerRecord, Base):
    __tablename__ = "traveller_profiles"
    __table_args__ = (
        company_scope("traveller_profile"),
        record_scope("traveller_profile"),
        CheckConstraint(
            "status IN ('active','review_required','blocked','deleted')",
            name="ck_traveller_profile_status",
        ),
        CheckConstraint(
            "revision >= 1 AND authorization_version >= 1 AND contact_revision >= 1",
            name="ck_traveller_profile_revisions",
        ),
        CheckConstraint(
            "reuse_permission_status IN ('unknown','granted','withdrawn')",
            name="ck_traveller_profile_permission",
        ),
        Index("ix_traveller_profile_directory", "agency_id", "company_id", "status", "id"),
        Index("ix_traveller_profile_retention", "retention_until", "id"),
        Index("ix_traveller_profile_permission", "reuse_permission_status", "id"),
        Index("ix_traveller_profile_name", "agency_id", "company_id", "fingerprint_key_version", "name_fingerprint", "id"),
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="review_required", server_default="review_required"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    authorization_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    contact_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    display_name_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fingerprint_key_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reuse_permission_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown", server_default="unknown"
    )
    reuse_permission_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TravellerIdentifierModel(TravellerRecord, Base):
    __tablename__ = "traveller_identifiers"
    __table_args__ = (
        traveller_scope("traveller_identifier"),
        record_scope("traveller_identifier"),
        CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL OR effective_until >= effective_from",
            name="ck_traveller_identifier_period",
        ),
        Index(
            "ix_traveller_identifier_match",
            "agency_id",
            "company_id",
            "identifier_type",
            "fingerprint_key_version",
            "value_fingerprint",
            "is_individual",
        ),
        Index("ix_traveller_identifier_person", "agency_id", "company_id", "traveller_id"),
    )
    traveller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    identifier_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    value_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    is_individual: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class TravellerContactBindingModel(TravellerRecord, Base):
    __tablename__ = "traveller_contact_bindings"
    __table_args__ = (
        traveller_scope("traveller_contact"),
        record_scope("traveller_contact"),
        CheckConstraint("kind IN ('phone','email')", name="ck_traveller_contact_kind"),
        CheckConstraint(
            "status IN ('current','historical','revoked')", name="ck_traveller_contact_status"
        ),
        CheckConstraint("revision >= 1", name="ck_traveller_contact_revision"),
        Index(
            "ix_traveller_contact_match",
            "agency_id",
            "company_id",
            "kind",
            "fingerprint_key_version",
            "value_fingerprint",
            "status",
        ),
        Index(
            "uq_traveller_contact_current",
            "traveller_id",
            "kind",
            unique=True,
            postgresql_where=text("status = 'current'"),
            sqlite_where=text("status = 'current'"),
        ),
        Index(
            "ix_traveller_contact_person", "agency_id", "company_id", "traveller_id", "created_at"
        ),
    )
    traveller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    value_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    value_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    is_shared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
