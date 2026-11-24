"""Canonical passenger submission fields, scope and review lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.value_objects.custom_questions import (
    CustomAnswerSnapshot,
    CustomDetailAnswerSnapshot,
)
from app.infrastructure.database.model_base import JSONB, Base, _utcnow
from app.infrastructure.database.search_index_sql import PASSPORT_SEARCH_SQL

if TYPE_CHECKING:
    from app.infrastructure.database._core_models.groups import ClientGroupModel


class PassportSubmissionModel(Base):
    __module__ = "app.infrastructure.database.models"
    __tablename__ = "passport_submissions"
    __table_args__ = (
        Index("ix_passport_submissions_scoped_seek", "agency_id", "group_id", "id"),
        Index("ix_passport_search_trgm", literal_column(PASSPORT_SEARCH_SQL).label("search_text"),
              postgresql_using="gin", postgresql_ops={"search_text": "gin_trgm_ops"}).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["group_id", "agency_id"],
            ["client_groups.id", "client_groups.agency_id"],
            name="fk_passport_submissions_group_agency",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "agency_id",
            "group_id",
            name="uq_passport_submissions_mobile_scope",
        ),
        Index(
            "ix_passport_submissions_mobile_roster",
            "agency_id",
            "group_id",
            "status",
            "id",
        ),
        Index(
            "ix_passport_submissions_agency_status_created_at",
            "agency_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_passport_submissions_group_status_created_at",
            "group_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_passport_submissions_group_email",
            "group_id",
            "client_email",
        ),
        Index(
            "ix_passport_submissions_group_phone",
            "group_id",
            "client_phone",
        ),
        Index(
            "ix_passport_submissions_mobile_phone_lookup",
            text(r"regexp_replace(coalesce(client_phone, ''), '\D', '', 'g')"),
            postgresql_where=text("client_reviewed_at IS NOT NULL"),
        ).ddl_if(dialect="postgresql"),
        UniqueConstraint(
            "group_id",
            "upload_idempotency_key",
            name="uq_passport_submissions_group_upload_key",
        ),
        CheckConstraint(
            "acquisition_mode IN ('camera', 'file')",
            name="ck_passport_submissions_acquisition_mode",
        ),
        CheckConstraint(
            "extraction_status IN ("
            "'not_started', 'processing', 'extraction_complete', "
            "'extraction_partial', 'extraction_failed', 'ready_for_review'"
            ")",
            name="ck_passport_submissions_extraction_status",
        ),
        CheckConstraint(
            "extraction_revision >= 0",
            name="ck_passport_submissions_extraction_revision",
        ),
        CheckConstraint(
            "post_submission_verification_revision >= 0",
            name="ck_passport_submissions_post_verification_revision",
        ),
        CheckConstraint(
            "("
            "qualifier_enabled_snapshot = false AND "
            "qualifier_selection_id IS NULL AND "
            "qualifier_is_self IS NULL AND "
            "qualifier_relation_code IS NULL AND "
            "qualifier_relation_label IS NULL AND "
            "qualifier_selected_at IS NULL"
            ") OR ("
            "qualifier_enabled_snapshot = true AND "
            "qualifier_selection_id IS NOT NULL AND "
            "qualifier_is_self IS NOT NULL AND "
            "qualifier_relation_label IS NOT NULL AND "
            "qualifier_selected_at IS NOT NULL AND ("
            "(qualifier_is_self = true AND "
            "qualifier_relation_code IS NULL AND "
            "qualifier_relation_label = 'Self') OR "
            "(qualifier_is_self = false AND "
            "qualifier_relation_code IS NOT NULL AND "
            "qualifier_relation_label <> 'Self')"
            ")"
            ")",
            name="ck_passport_submissions_qualifier_snapshot",
        ),
        CheckConstraint(
            "qualifier_relation_code IS NULL OR qualifier_relation_code IN ("
            "'spouse', 'husband', 'wife', 'brother', 'sister', 'son', "
            "'daughter', 'father', 'mother', 'parent', 'child', "
            "'grandfather', 'grandmother', 'grandson', 'granddaughter', "
            "'father_in_law', 'mother_in_law', 'brother_in_law', "
            "'sister_in_law', 'son_in_law', 'daughter_in_law', "
            "'legal_guardian', 'other'"
            ")",
            name="ck_passport_submissions_qualifier_relation_code",
        ),
        CheckConstraint(
            "qualifier_relation_code <> 'other' OR ("
            "qualifier_relation_label IS NOT NULL AND "
            "length(trim(qualifier_relation_label)) BETWEEN 1 AND 100 AND "
            "lower(trim(qualifier_relation_label)) <> 'self')",
            name="ck_passport_submissions_qualifier_other_text",
        ),
        UniqueConstraint(
            "qualifier_selection_id",
            name="uq_passport_submissions_qualifier_selection",
        ),
        ForeignKeyConstraint(
            ["qualifier_selection_id", "group_id"],
            ["qualifier_selections.id", "qualifier_selections.group_id"],
            name="fk_passport_submissions_qualifier_selection",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Optional office label; original client_name remains the contact identity.
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    departure_city: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    nearest_domestic_airport: Mapped[str | None] = mapped_column(String(120), nullable=True)
    submission_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="single", server_default="single"
    )
    family_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    family_member_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    family_relation: Mapped[str | None] = mapped_column(String(80), nullable=True)
    family_gender: Mapped[str | None] = mapped_column(String(40), nullable=True)
    family_head_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    family_head_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    family_head_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    family_broadcast_to_member: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    image_s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    thumbnail_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Excel-derived organisational attributes (staff code, zone, designation,
    # etc.) are kept separately from passport OCR fields.
    staff_metadata: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    document_follow_up: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    custom_answers: Mapped[list[CustomAnswerSnapshot]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    custom_detail_answers: Mapped[list[CustomDetailAnswerSnapshot]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    passport_photo_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    passport_cover_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    passport_back_cover_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    passport_back_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    acquisition_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="file", server_default="file"
    )
    upload_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    qualifier_enabled_snapshot: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    qualifier_selection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    qualifier_is_self: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    qualifier_relation_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    qualifier_relation_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    qualifier_selected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    extraction_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_started", server_default="not_started"
    )
    extraction_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "pending_upload",
            "uploaded",
            "processing",
            "review_required",
            "client_submitted",
            "confirmed",
            "failed",
            "pending_extraction",
            "extracting",
            "ready_for_client_review",
            "submitted",
            "ai_approved",
            "needs_review",
            "staff_approved",
            name="submission_status_enum",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
        default="uploaded",
        index=True,
    )
    extracted_fields: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    confirmed_fields: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    extraction_conflicts: Mapped[list[dict[str, str | None]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_score: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    mrz_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    client_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    post_submission_verification: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    post_submission_verification_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    post_submission_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    verification_reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    verification_reviewer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    group: Mapped[ClientGroupModel] = relationship(
        "ClientGroupModel", back_populates="submissions",
        primaryjoin="and_(ClientGroupModel.id == PassportSubmissionModel.group_id, "
                    "ClientGroupModel.agency_id == PassportSubmissionModel.agency_id)",
    )
