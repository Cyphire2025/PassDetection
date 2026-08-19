"""SQLAlchemy ORM models exposed through the stable database facade."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE
from app.infrastructure.database import communications_models as _communications_models
from app.infrastructure.database import document_models as _document_models
from app.infrastructure.database import operations_models as _operations_models
from app.infrastructure.database.model_base import JSONB, Base, _utcnow

WhatsAppBroadcastGroupModel = _communications_models.WhatsAppBroadcastGroupModel
WhatsAppBroadcastRecipientModel = _communications_models.WhatsAppBroadcastRecipientModel
WhatsAppBroadcastRejectedContactModel = _communications_models.WhatsAppBroadcastRejectedContactModel
WhatsAppBroadcastSupportContactModel = _communications_models.WhatsAppBroadcastSupportContactModel
WhatsAppMessageLogModel = _communications_models.WhatsAppMessageLogModel
WhatsAppRecipientMessageStateModel = _communications_models.WhatsAppRecipientMessageStateModel
DocumentDistributionBatchModel = _document_models.DocumentDistributionBatchModel
DistributedDocumentModel = _document_models.DistributedDocumentModel
DocumentWhatsAppDeliveryModel = _document_models.DocumentWhatsAppDeliveryModel
DocumentRenameBatchModel = _document_models.DocumentRenameBatchModel
DocumentRenameItemModel = _document_models.DocumentRenameItemModel
DocumentUploadChunkModel = _document_models.DocumentUploadChunkModel
StorageCleanupJobModel = _document_models.StorageCleanupJobModel
AttendanceRecordModel = _operations_models.AttendanceRecordModel
AttendanceSessionModel = _operations_models.AttendanceSessionModel
PassengerQRTokenModel = _operations_models.PassengerQRTokenModel
PassengerQrWhatsAppDeliveryModel = _operations_models.PassengerQrWhatsAppDeliveryModel
RoomingAssignmentModel = _operations_models.RoomingAssignmentModel
RoomingCheckinModel = _operations_models.RoomingCheckinModel
RoomingHotelModel = _operations_models.RoomingHotelModel
RoomingHotelPassengerModel = _operations_models.RoomingHotelPassengerModel
RoomingPassengerPreferenceModel = _operations_models.RoomingPassengerPreferenceModel
RoomingRoomModel = _operations_models.RoomingRoomModel


class AgencyModel(Base):
    __tablename__ = "agencies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    users: Mapped[list[UserModel]] = relationship("UserModel", back_populates="agency")
    client_groups: Mapped[list[ClientGroupModel]] = relationship(
        "ClientGroupModel", back_populates="agency"
    )


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum(
            "super_admin",
            "agency_admin",
            "agency_manager",
            "agency_staff",
            "agency_coordinator",
            "client_manager",
            name="user_role_enum",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
    )
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agency: Mapped[AgencyModel | None] = relationship("AgencyModel", back_populates="users")
    refresh_tokens: Mapped[list[RefreshTokenModel]] = relationship(
        "RefreshTokenModel", back_populates="user", cascade="all, delete-orphan"
    )


class RefreshTokenModel(Base):
    """
    Stores issued refresh tokens.

    Storing them in the DB allows:
      - Token revocation (logout, compromise response)
      - Rotation detection (detect replay attacks)
      - Audit trail of auth events
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    # Track which IP created this token for audit purposes
    created_from_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[UserModel] = relationship("UserModel", back_populates="refresh_tokens")


class ClientGroupModel(Base):
    __tablename__ = "client_groups"
    __table_args__ = (
        CheckConstraint(
            "length(timezone) BETWEEN 1 AND 64 AND timezone = trim(timezone)",
            name="ck_client_groups_timezone_shape",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "active",
            "closed",
            "archived",
            "deleted",
            name="group_status_enum",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
        default="active",
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(255), nullable=True)
    travel_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    return_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=DEFAULT_TRIP_TIMEZONE,
        server_default=DEFAULT_TRIP_TIMEZONE,
    )
    package_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    departure_cities: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    base_city_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    nearest_international_airport_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    staff_code_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    agent_employee_code_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    meal_preference_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    require_selfie: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    allow_files_from_device: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    ask_nearest_domestic_airport: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    relation_with_qualifier_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    designation_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    agency_dealership_name_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    custom_questions: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    custom_details: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_passport_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deletion_retained_records: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    agency: Mapped[AgencyModel] = relationship("AgencyModel", back_populates="client_groups")
    submissions: Mapped[list[PassportSubmissionModel]] = relationship(
        "PassportSubmissionModel", back_populates="group"
    )
    whatsapp_broadcast_links: Mapped[list[ClientGroupWhatsAppBroadcastLinkModel]] = relationship(
        "ClientGroupWhatsAppBroadcastLinkModel",
        back_populates="client_group",
        cascade="all, delete-orphan",
    )


class ManagerGroupAccessModel(Base):
    __tablename__ = "manager_group_access"
    __table_args__ = (
        UniqueConstraint("manager_id", "group_id", name="uq_manager_group_access_manager_group"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )




class CoordinatorAssignmentModel(Base):
    __tablename__ = "coordinator_assignments"
    __table_args__ = (
        Index("ix_coordinator_assignments_active_group", "agency_id", "group_id", "active"),
        Index("ix_coordinator_assignments_coordinator_active", "coordinator_user_id", "active"),
        Index("ix_coordinator_assignments_passenger_active", "passenger_id", "active"),
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
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CoordinatorGroupAssignmentModel(Base):
    __tablename__ = "coordinator_group_assignments"
    __table_args__ = (
        Index("ix_coordinator_group_assignments_group_active", "group_id", "active"),
        Index(
            "ix_coordinator_group_assignments_coordinator_active", "coordinator_user_id", "active"
        ),
        Index(
            "uq_coordinator_group_assignments_active_pair",
            "group_id",
            "coordinator_user_id",
            unique=True,
            postgresql_where=text("active = true"),
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
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PassportSubmissionModel(Base):
    __tablename__ = "passport_submissions"
    __table_args__ = (
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
            "'legal_guardian'"
            ")",
            name="ck_passport_submissions_qualifier_relation_code",
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
    staff_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    custom_answers: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    custom_detail_answers: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    passport_photo_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
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
    qualifier_relation_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
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
    extracted_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confirmed_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extraction_conflicts: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_score: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
    post_submission_verification: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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

    group: Mapped[ClientGroupModel] = relationship("ClientGroupModel", back_populates="submissions")


class PassportExportHistoryModel(Base):
    """Two-phase, immutable checkpoint for one group export."""

    __tablename__ = "passport_export_history"
    __table_args__ = (
        UniqueConstraint(
            "group_id",
            "export_kind",
            "request_id",
            name="uq_passport_export_history_group_kind_request",
        ),
        CheckConstraint(
            "export_kind IN ('passport_images', 'passport_excel')",
            name="ck_passport_export_history_kind",
        ),
        CheckConstraint(
            "export_mode IN ('all', 'incremental')",
            name="ck_passport_export_history_mode",
        ),
        CheckConstraint(
            "total_available_count >= 0 AND exported_count >= 0 AND pending_recipient_count >= 0",
            name="ck_passport_export_history_counts",
        ),
        CheckConstraint(
            "format_version >= 1",
            name="ck_passport_export_history_format_version",
        ),
        CheckConstraint(
            "(status = 'prepared' AND completed_at IS NULL) "
            "OR (status = 'completed' AND completed_at IS NOT NULL)",
            name="ck_passport_export_history_completion",
        ),
        Index(
            "ix_passport_export_history_group_kind_created",
            "group_id",
            "export_kind",
            "created_at",
        ),
        Index(
            "ix_passport_export_history_group_kind_status_completed",
            "group_id",
            "export_kind",
            "status",
            "completed_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    export_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    export_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    format_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    baseline_export_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_export_history.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The cumulative checkpoint is deliberately separate from the file payload.
    # An incremental file may contain 19 people while its checkpoint represents
    # all 189 people available when that file was prepared.
    snapshot_submission_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    exported_submission_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    exported_people_snapshot: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    total_available_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    exported_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    pending_recipient_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    artifact_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="prepared", server_default="prepared"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PassportRosterResolutionModel(Base):
    """Auditable resolution of an upload that did not match a broadcast recipient."""

    __tablename__ = "passport_roster_resolutions"
    __table_args__ = (
        UniqueConstraint(
            "client_group_id",
            "request_id",
            name="uq_passport_roster_resolution_group_request",
        ),
        CheckConstraint(
            "resolution_type IN ('replacement', 'rejected')",
            name="ck_passport_roster_resolution_type",
        ),
        CheckConstraint(
            "status IN ('active', 'restored')",
            name="ck_passport_roster_resolution_status",
        ),
        CheckConstraint(
            "(status = 'active' AND restored_at IS NULL) "
            "OR (status = 'restored' AND restored_at IS NOT NULL)",
            name="ck_passport_roster_resolution_restored_at",
        ),
        CheckConstraint(
            "(resolution_type = 'replacement' "
            "AND replaced_recipient_normalized_phone IS NOT NULL "
            "AND original_recipient_phone IS NOT NULL "
            "AND (status = 'restored' OR broadcast_recipient_id IS NOT NULL)) "
            "OR (resolution_type = 'rejected' "
            "AND broadcast_recipient_id IS NULL "
            "AND replaced_recipient_normalized_phone IS NULL)",
            name="ck_passport_roster_resolution_recipient",
        ),
        Index(
            "ix_passport_roster_resolutions_group_status_created",
            "client_group_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_passport_roster_resolutions_active_phone",
            "agency_id",
            "client_group_id",
            "replaced_recipient_normalized_phone",
            postgresql_where=text("status = 'active' AND resolution_type = 'replacement'"),
            sqlite_where=text("status = 'active' AND resolution_type = 'replacement'"),
        ),
        Index(
            "uq_passport_roster_resolutions_active_submission",
            "submission_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "uq_passport_roster_resolutions_active_recipient",
            "broadcast_recipient_id",
            unique=True,
            postgresql_where=text("status = 'active' AND broadcast_recipient_id IS NOT NULL"),
            sqlite_where=text("status = 'active' AND broadcast_recipient_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    broadcast_recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_recipients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    replaced_recipient_normalized_phone: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    original_recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_recipient_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_recipient_imported_fields: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    resolution_type: Mapped[str] = mapped_column(String(24), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    suppressed_recipient_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    excluded_submission_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    restored_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PassportImageCropModel(Base):
    """Non-destructive image-edit metadata and its revisioned display derivative."""

    __tablename__ = "passport_image_crops"
    __table_args__ = (
        UniqueConstraint(
            "submission_id", "image_type", name="uq_passport_image_crops_submission_type"
        ),
        CheckConstraint(
            "image_type IN ('visa_photo', 'passport_front', 'passport_back')",
            name="ck_passport_image_crops_type",
        ),
        CheckConstraint(
            "rotation_degrees >= 0 AND rotation_degrees <= 359",
            name="ck_passport_image_crops_rotation",
        ),
        CheckConstraint(
            "crop_x >= 0 AND crop_y >= 0 AND crop_width >= 0.08 AND crop_height >= 0.08 "
            "AND crop_x + crop_width <= 1.000001 AND crop_y + crop_height <= 1.000001",
            name="ck_passport_image_crops_bounds",
        ),
        CheckConstraint(
            "source_width > 0 AND source_height > 0", name="ck_passport_image_crops_source_size"
        ),
        CheckConstraint(
            "sharpness >= 1.0 AND sharpness <= 3.0",
            name="ck_passport_image_crops_sharpness",
        ),
        CheckConstraint(
            "sharpness_algorithm_version IN (1, 2)",
            name="ck_passport_image_crops_sharpness_algorithm_version",
        ),
        CheckConstraint("revision > 0", name="ck_passport_image_crops_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    image_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    edit_source_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    derived_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    crop_x: Mapped[float] = mapped_column(Float, nullable=False)
    crop_y: Mapped[float] = mapped_column(Float, nullable=False)
    crop_width: Mapped[float] = mapped_column(Float, nullable=False)
    crop_height: Mapped[float] = mapped_column(Float, nullable=False)
    rotation_degrees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sharpness: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
        server_default="1.0",
    )
    sharpness_algorithm_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    source_width: Mapped[int] = mapped_column(Integer, nullable=False)
    source_height: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PassportVisaAiImageModel(Base):
    """Durable AI variants for one submission's Visa photograph."""

    __tablename__ = "passport_visa_ai_images"
    __table_args__ = (
        Index(
            "ix_passport_visa_ai_images_submission_created",
            "submission_id",
            "created_at",
        ),
        UniqueConstraint(
            "submission_id",
            "generated_storage_key",
            name="uq_passport_visa_ai_images_submission_storage_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_source_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    input_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    generated_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    prompt: Mapped[str] = mapped_column(String(1000), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )


class PassportVisaAiImageJobModel(Base):
    """Durable queue state for slow Visa-photo AI generation."""

    __tablename__ = "passport_visa_ai_image_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_passport_visa_ai_image_jobs_status",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="ck_passport_visa_ai_image_jobs_attempts",
        ),
        CheckConstraint(
            "max_attempts BETWEEN 1 AND 3",
            name="ck_passport_visa_ai_image_jobs_max_attempts",
        ),
        Index(
            "uq_passport_visa_ai_image_jobs_active_submission",
            "submission_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index(
            "ix_passport_visa_ai_image_jobs_submission_created",
            "submission_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_source_storage_key: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    input_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    prompt: Mapped[str] = mapped_column(String(1000), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="queued",
        server_default="queued",
        index=True,
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2,
        server_default="2",
    )
    celery_task_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    result_image_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_visa_ai_images.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(320), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


class QualifierSelectionModel(Base):
    __tablename__ = "qualifier_selections"
    __table_args__ = (
        CheckConstraint(
            "("
            "is_self = true AND relation_code IS NULL AND relation_label = 'Self'"
            ") OR ("
            "is_self = false AND relation_code IS NOT NULL AND relation_label <> 'Self'"
            ")",
            name="ck_qualifier_selections_choice",
        ),
        CheckConstraint(
            "expires_at > selected_at",
            name="ck_qualifier_selections_expiry",
        ),
        CheckConstraint(
            "relation_code IS NULL OR relation_code IN ("
            "'spouse', 'husband', 'wife', 'brother', 'sister', 'son', "
            "'daughter', 'father', 'mother', 'parent', 'child', "
            "'grandfather', 'grandmother', 'grandson', 'granddaughter', "
            "'father_in_law', 'mother_in_law', 'brother_in_law', "
            "'sister_in_law', 'son_in_law', 'daughter_in_law', "
            "'legal_guardian'"
            ")",
            name="ck_qualifier_selections_relation_code",
        ),
        Index(
            "ix_qualifier_selections_group_expires",
            "group_id",
            "expires_at",
        ),
        UniqueConstraint(
            "id",
            "group_id",
            name="uq_qualifier_selections_id_group",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    is_self: Mapped[bool] = mapped_column(Boolean, nullable=False)
    relation_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    relation_label: Mapped[str] = mapped_column(String(80), nullable=False)
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )






class PassportProcessingJobModel(Base):
    __tablename__ = "passport_processing_jobs"
    __table_args__ = (
        CheckConstraint(
            "extraction_revision >= 0",
            name="ck_passport_processing_jobs_extraction_revision",
        ),
        Index(
            "uq_passport_processing_jobs_active_revision",
            "submission_id",
            "extraction_revision",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    queue_name: Mapped[str] = mapped_column(String(64), nullable=False, default="passport_ocr")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    extraction_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    current_stage: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class ClientGroupWhatsAppBroadcastLinkModel(Base):
    """Tenant-scoped metadata link between an upload group and WhatsApp list."""

    __tablename__ = "client_group_whatsapp_broadcast_links"
    __table_args__ = (
        UniqueConstraint(
            "client_group_id",
            "broadcast_group_id",
            name="uq_client_group_whatsapp_broadcast_link",
        ),
        Index(
            "ix_client_group_whatsapp_links_agency_group",
            "agency_id",
            "client_group_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    broadcast_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    client_group: Mapped[ClientGroupModel] = relationship(
        "ClientGroupModel", back_populates="whatsapp_broadcast_links"
    )
    broadcast_group: Mapped[WhatsAppBroadcastGroupModel] = relationship(
        "WhatsAppBroadcastGroupModel", back_populates="client_group_links"
    )


class PassportPostSubmissionVerificationJobModel(Base):
    __tablename__ = "passport_post_submission_verification_jobs"
    __table_args__ = (
        UniqueConstraint(
            "submission_id",
            "verification_revision",
            name="uq_passport_post_verification_job_revision",
        ),
        CheckConstraint(
            "verification_revision >= 1",
            name="ck_passport_post_verification_revision",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_passport_post_verification_job_status",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="ck_passport_post_verification_job_attempts",
        ),
        CheckConstraint(
            "max_attempts BETWEEN 1 AND 3",
            name="ck_passport_post_verification_job_max_attempts",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    verification_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="queued",
        server_default="queued",
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )


class NotificationModel(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "dedupe_key",
            name="uq_notifications_user_dedupe_key",
        ),
        Index(
            "ix_notifications_user_unread_created",
            "user_id",
            "is_read",
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
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    priority: Mapped[str] = mapped_column(
        String(16),
        default="normal",
        server_default="normal",
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(
        String(40),
        default="general",
        server_default="general",
        nullable=False,
        index=True,
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformSettingModel(Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
