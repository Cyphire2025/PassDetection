"""
SQLAlchemy ORM Models — Updated for Phase 2
============================================
Added: RefreshTokenModel for storing revocable refresh tokens.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
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
from sqlalchemy.dialects.postgresql import JSONB as PostgreSQLJSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONB = JSON().with_variant(PostgreSQLJSONB, "postgresql")


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


class AgencyModel(Base):
    __tablename__ = "agencies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    users: Mapped[list[UserModel]] = relationship("UserModel", back_populates="agency")
    client_groups: Mapped[list[ClientGroupModel]] = relationship("ClientGroupModel", back_populates="agency")


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    # Track which IP created this token for audit purposes
    created_from_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[UserModel] = relationship("UserModel", back_populates="refresh_tokens")


class ClientGroupModel(Base):
    __tablename__ = "client_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum("active", "closed", "archived", "deleted", name="group_status_enum", native_enum=True, create_type=False),
        nullable=False, default="active",
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(255), nullable=True)
    travel_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    return_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    package_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    departure_cities: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    base_city_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    nearest_international_airport_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    staff_code_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    meal_preference_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    require_selfie: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    allow_files_from_device: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    ask_nearest_domestic_airport: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    relation_with_qualifier_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_passport_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deletion_retained_records: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    agency: Mapped[AgencyModel] = relationship("AgencyModel", back_populates="client_groups")
    submissions: Mapped[list[PassportSubmissionModel]] = relationship(
        "PassportSubmissionModel", back_populates="group"
    )
    whatsapp_broadcast_links: Mapped[
        list[ClientGroupWhatsAppBroadcastLinkModel]
    ] = relationship(
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
        UUID(as_uuid=True), ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class WhatsAppBroadcastGroupModel(Base):
    __tablename__ = "whatsapp_broadcast_groups"
    __table_args__ = (
        Index("ix_whatsapp_broadcast_groups_agency_created", "agency_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    organizing_company_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    recipient_opt_in_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    client_group_links: Mapped[
        list[ClientGroupWhatsAppBroadcastLinkModel]
    ] = relationship(
        "ClientGroupWhatsAppBroadcastLinkModel",
        back_populates="broadcast_group",
        cascade="all, delete-orphan",
    )


class WhatsAppBroadcastRecipientModel(Base):
    __tablename__ = "whatsapp_broadcast_recipients"
    __table_args__ = (
        UniqueConstraint("broadcast_group_id", "normalized_phone_number", name="uq_whatsapp_recipient_group_phone"),
        Index("ix_whatsapp_recipients_group_created", "broadcast_group_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broadcast_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone_number: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_phone_number: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    imported_fields: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class WhatsAppBroadcastSupportContactModel(Base):
    __tablename__ = "whatsapp_broadcast_support_contacts"
    __table_args__ = (
        UniqueConstraint(
            "broadcast_group_id",
            "normalized_phone_number",
            name="uq_whatsapp_support_group_phone",
        ),
        Index("ix_whatsapp_support_group_order", "broadcast_group_id", "sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broadcast_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class WhatsAppMessageLogModel(Base):
    __tablename__ = "whatsapp_message_logs"
    __table_args__ = (
        Index("ix_whatsapp_message_logs_group_created", "broadcast_group_id", "created_at"),
        Index(
            "uq_whatsapp_active_explicit_resend",
            "recipient_id",
            "message_type",
            unique=True,
            postgresql_where=text(
                "is_explicit_resend = true "
                "AND status IN ('queued', 'processing', 'delivery_unknown')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    broadcast_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("whatsapp_broadcast_recipients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    status_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    provider_status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rendered_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    header_parameter_values: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    template_parameter_values: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    is_explicit_resend: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class WhatsAppRecipientMessageStateModel(Base):
    """Atomic per-recipient/per-message-type delivery claim and checklist."""

    __tablename__ = "whatsapp_recipient_message_states"
    __table_args__ = (
        UniqueConstraint(
            "recipient_id",
            "message_type",
            name="uq_whatsapp_recipient_message_state",
        ),
        Index(
            "ix_whatsapp_message_states_group_type_status",
            "broadcast_group_id",
            "message_type",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broadcast_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_recipients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    provider_status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
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
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("passport_submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CoordinatorGroupAssignmentModel(Base):
    __tablename__ = "coordinator_group_assignments"
    __table_args__ = (
        Index("ix_coordinator_group_assignments_group_active", "group_id", "active"),
        Index("ix_coordinator_group_assignments_coordinator_active", "coordinator_user_id", "active"),
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
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PassportSubmissionModel(Base):
    __tablename__ = "passport_submissions"
    __table_args__ = (
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
        UUID(as_uuid=True), ForeignKey("client_groups.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    departure_city: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    nearest_domestic_airport: Mapped[str | None] = mapped_column(String(120), nullable=True)
    submission_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="single", server_default="single")
    family_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    family_member_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    family_relation: Mapped[str | None] = mapped_column(String(80), nullable=True)
    family_gender: Mapped[str | None] = mapped_column(String(40), nullable=True)
    family_head_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    family_head_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    family_head_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    family_broadcast_to_member: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    image_s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    thumbnail_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Excel-derived organisational attributes (staff code, zone, designation,
    # etc.) are kept separately from passport OCR fields.
    staff_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
            "pending_upload", "uploaded", "processing",
            "review_required", "client_submitted", "confirmed", "failed",
            "pending_extraction", "extracting", "ready_for_client_review",
            "submitted", "ai_approved", "needs_review", "staff_approved",
            name="submission_status_enum",
            native_enum=True,
            create_type=False,
        ),
        nullable=False, default="uploaded", index=True,
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    client_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class DocumentDistributionBatchModel(Base):
    __tablename__ = "document_distribution_batches"
    __table_args__ = (
        Index("ix_document_batches_group_type_created", "group_id", "document_type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False, index=True
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class DistributedDocumentModel(Base):
    __tablename__ = "distributed_documents"
    __table_args__ = (
        Index("ix_distributed_documents_batch_passenger", "batch_id", "passenger_id"),
        Index("ix_distributed_documents_group_type", "group_id", "document_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_distribution_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    passenger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("passport_submissions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False, default="application/pdf")
    detected_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    match_status: Mapped[str] = mapped_column(String(40), nullable=False, default="needs_review", index=True)
    match_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    match_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted_passport_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    extracted_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class DocumentRenameBatchModel(Base):
    __tablename__ = "document_rename_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class DocumentRenameItemModel(Base):
    __tablename__ = "document_rename_items"
    __table_args__ = (
        Index("ix_document_rename_items_batch_created", "batch_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_rename_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    renamed_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False, default="application/pdf")
    detected_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)
    extracted_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted_passport_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    extracted_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="renamed", index=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class RoomingHotelModel(Base):
    __tablename__ = "rooming_hotels"
    __table_args__ = (
        Index("ix_rooming_hotels_group_created", "group_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hotel_name: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    check_in_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    check_out_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class RoomingRoomModel(Base):
    __tablename__ = "rooming_rooms"
    __table_args__ = (
        UniqueConstraint("hotel_id", "room_number", name="uq_rooming_rooms_hotel_number"),
        Index("ix_rooming_rooms_hotel_number", "hotel_id", "room_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rooming_hotels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    room_number: Mapped[str] = mapped_column(String(32), nullable=False)
    room_type: Mapped[str] = mapped_column(String(16), nullable=False, default="twin")
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    allocation_tag: Mapped[str] = mapped_column(String(16), nullable=False, default="mixed")
    roommate_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_saved: Mapped[bool] = mapped_column(default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class RoomingPassengerPreferenceModel(Base):
    __tablename__ = "rooming_passenger_preferences"
    __table_args__ = (
        UniqueConstraint("hotel_id", "passenger_id", name="uq_rooming_preferences_hotel_passenger"),
        Index("ix_rooming_preferences_hotel_passenger", "hotel_id", "passenger_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rooming_hotels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("passport_submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    allocation_tag: Mapped[str] = mapped_column(String(16), nullable=False, default="unspecified")
    special_requests: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    roommate_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class RoomingAssignmentModel(Base):
    __tablename__ = "rooming_assignments"
    __table_args__ = (
        UniqueConstraint("hotel_id", "passenger_id", name="uq_rooming_assignments_hotel_passenger"),
        UniqueConstraint("room_id", "passenger_id", name="uq_rooming_assignments_room_passenger"),
        Index("ix_rooming_assignments_room_position", "room_id", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rooming_hotels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rooming_rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("passport_submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class RoomingCheckinModel(Base):
    __tablename__ = "rooming_checkins"
    __table_args__ = (
        UniqueConstraint("hotel_id", "passenger_id", name="uq_rooming_checkins_hotel_passenger"),
        Index("ix_rooming_checkins_hotel_status", "hotel_id", "checked_in", "key_issued", "welcome_letter_issued"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True)
    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rooming_hotels.id", ondelete="CASCADE"), nullable=False, index=True)
    room_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rooming_rooms.id", ondelete="CASCADE"), nullable=False, index=True)
    passenger_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("passport_submissions.id", ondelete="CASCADE"), nullable=False, index=True)
    checked_in: Mapped[bool] = mapped_column(default=False, nullable=False)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    key_issued: Mapped[bool] = mapped_column(default=False, nullable=False)
    key_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    welcome_letter_issued: Mapped[bool] = mapped_column(default=False, nullable=False)
    welcome_letter_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class PassengerQRTokenModel(Base):
    __tablename__ = "passenger_qr_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_passenger_qr_tokens_token_hash"),
        Index("ix_passenger_qr_tokens_active_passenger", "passenger_id", "is_active"),
        Index("ix_passenger_qr_tokens_agency_active", "agency_id", "is_active"),
        Index(
            "uq_passenger_qr_tokens_one_active_per_passenger",
            "passenger_id",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("passport_submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    qr_payload: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class AttendanceSessionModel(Base):
    __tablename__ = "attendance_sessions"
    __table_args__ = (
        Index("ix_attendance_sessions_group_status", "group_id", "status"),
        Index("ix_attendance_sessions_agency_created", "agency_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("draft", "active", "completed", "cancelled", name="attendance_session_status_enum", native_enum=True, create_type=False),
        nullable=False,
        default="draft",
        index=True,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AttendanceRecordModel(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("session_id", "passenger_id", name="uq_attendance_records_session_passenger"),
        UniqueConstraint("session_id", "client_event_id", name="uq_attendance_records_session_client_event"),
        Index("ix_attendance_records_agency_session", "agency_id", "session_id"),
        Index("ix_attendance_records_coordinator_scanned", "coordinator_user_id", "scanned_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attendance_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("passport_submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sync_source: Mapped[str] = mapped_column(
        Enum("online", "offline", name="attendance_scan_source_enum", native_enum=True, create_type=False),
        nullable=False,
        default="online",
    )
    client_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


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
        UUID(as_uuid=True), ForeignKey("passport_submissions.id", ondelete="CASCADE"), nullable=False, index=True
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


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

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
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
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
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
    agency_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)


class NotificationModel(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformSettingModel(Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
