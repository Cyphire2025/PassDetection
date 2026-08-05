"""Persistence models for the native Group Companion application.

The mobile API is intentionally backed by explicit, tenant-scoped records
instead of reusing broad dashboard roles or serializing administrative ORM
objects.  Secrets stored here are hashes or application-encrypted bytes; raw
OTP codes, refresh tokens, push tokens, document URLs, and QR secrets do not
belong in these tables.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models import JSONB, Base


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class ClientOrganizationModel(Base):
    """One client/company inside an agency; never grants group access itself."""

    __tablename__ = "client_organizations"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", name="uq_client_org_id_agency"),
        CheckConstraint(
            "status IN ('active', 'inactive', 'deleted')",
            name="ck_client_org_status",
        ),
        CheckConstraint(
            "(status = 'deleted' AND deleted_at IS NOT NULL) OR "
            "(status != 'deleted' AND deleted_at IS NULL)",
            name="ck_client_org_deleted_shape",
        ),
        Index(
            "uq_client_org_agency_name_live",
            "agency_id",
            "normalized_name",
            unique=True,
            postgresql_where=text("status != 'deleted'"),
            sqlite_where=text("status != 'deleted'"),
        ),
        Index(
            "uq_client_org_agency_external_ref",
            "agency_id",
            "external_reference",
            unique=True,
            postgresql_where=text("external_reference IS NOT NULL"),
            sqlite_where=text("external_reference IS NOT NULL"),
        ),
        Index("ix_client_org_agency_status", "agency_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClientManagerProfileModel(Base):
    """Client-side manager metadata layered on the shared user credential record."""

    __tablename__ = "client_manager_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_client_manager_profile_user"),
        UniqueConstraint("id", "agency_id", name="uq_client_manager_profile_agency"),
        UniqueConstraint(
            "id",
            "agency_id",
            "organization_id",
            name="uq_client_manager_profile_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "agency_id"],
            ["client_organizations.id", "client_organizations.agency_id"],
            name="fk_client_manager_profile_org",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'deleted')",
            name="ck_client_manager_profile_status",
        ),
        CheckConstraint("revision >= 1", name="ck_client_manager_profile_revision"),
        CheckConstraint(
            "access_generation >= 0",
            name="ck_client_manager_profile_generation",
        ),
        CheckConstraint(
            "length(normalized_phone_number) BETWEEN 9 AND 16 "
            "AND normalized_phone_number LIKE '+%'",
            name="ck_client_manager_profile_phone",
        ),
        CheckConstraint(
            "(invitation_token_hash IS NULL) = (invitation_expires_at IS NULL)",
            name="ck_client_manager_profile_invitation_pair",
        ),
        CheckConstraint(
            "(status = 'active' AND activated_at IS NOT NULL "
            "AND suspended_at IS NULL AND deleted_at IS NULL) OR "
            "(status = 'invited' AND activated_at IS NULL "
            "AND suspended_at IS NULL AND deleted_at IS NULL) OR "
            "(status = 'suspended' AND suspended_at IS NOT NULL "
            "AND deleted_at IS NULL) OR "
            "(status = 'deleted' AND deleted_at IS NOT NULL)",
            name="ck_client_manager_profile_state_shape",
        ),
        Index(
            "uq_client_manager_phone_live",
            "agency_id",
            "normalized_phone_number",
            unique=True,
            postgresql_where=text("status != 'deleted'"),
            sqlite_where=text("status != 'deleted'"),
        ),
        Index("ix_client_manager_org_status", "organization_id", "status"),
        Index(
            "ix_client_manager_admin_list",
            "agency_id",
            "created_at",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    normalized_phone_number: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="invited", server_default="invited"
    )
    force_password_change: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    invitation_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invitation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GCGroupAccessModel(Base):
    """Deny-by-default mobile availability and version state for one group."""

    __tablename__ = "gc_group_access"
    __table_args__ = (
        UniqueConstraint("group_id", name="uq_gc_group_access_group"),
        UniqueConstraint("id", "agency_id", "group_id", name="uq_gc_group_access_scope"),
        UniqueConstraint(
            "id",
            "agency_id",
            "group_id",
            "client_organization_id",
            name="uq_gc_group_access_org_scope",
        ),
        ForeignKeyConstraint(
            ["client_organization_id", "agency_id"],
            ["client_organizations.id", "client_organizations.agency_id"],
            name="fk_gc_group_access_org",
            ondelete="RESTRICT",
        ),
        CheckConstraint("revision >= 1", name="ck_gc_group_access_revision"),
        CheckConstraint("access_generation >= 0", name="ck_gc_group_access_generation"),
        CheckConstraint(
            "manifest_version >= 0 AND itinerary_version >= 0 "
            "AND common_document_version >= 0 AND announcement_version >= 0 "
            "AND rooming_version >= 0 AND meal_version >= 0 AND qr_version >= 0",
            name="ck_gc_group_access_versions",
        ),
        CheckConstraint(
            "access_expires_at IS NULL OR access_starts_at IS NULL "
            "OR access_expires_at > access_starts_at",
            name="ck_gc_group_access_window",
        ),
        CheckConstraint(
            "NOT client_manager_access_enabled OR client_organization_id IS NOT NULL",
            name="ck_gc_group_access_manager_org",
        ),
        Index("ix_gc_group_access_agency_enabled", "agency_id", "is_enabled"),
        Index("ix_gc_group_access_window", "access_starts_at", "access_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    passenger_access_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    client_manager_access_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    coordinator_access_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    access_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    access_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    access_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    manifest_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    itinerary_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    common_document_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    announcement_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    rooming_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    meal_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    qr_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class ClientManagerGroupAssignmentModel(Base):
    """An explicit manager-to-group grant; organization membership is insufficient."""

    __tablename__ = "client_manager_group_assignments"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "gc_group_access_id",
            name="uq_client_manager_group_assignment",
        ),
        ForeignKeyConstraint(
            ["profile_id", "agency_id", "organization_id"],
            [
                "client_manager_profiles.id",
                "client_manager_profiles.agency_id",
                "client_manager_profiles.organization_id",
            ],
            name="fk_client_manager_assignment_profile",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id", "organization_id"],
            [
                "gc_group_access.id",
                "gc_group_access.agency_id",
                "gc_group_access.group_id",
                "gc_group_access.client_organization_id",
            ],
            name="fk_client_manager_assignment_group",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(is_active AND revoked_at IS NULL AND revoked_by_user_id IS NULL) OR "
            "(NOT is_active AND revoked_at IS NOT NULL)",
            name="ck_client_manager_assignment_state",
        ),
        Index("ix_client_manager_assignment_profile", "profile_id", "is_active"),
        Index("ix_client_manager_assignment_group", "gc_group_access_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    can_view_passenger_names: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    personal_document_access_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GCCommonDocumentModel(Base):
    """One immutable version of a common, non-passenger-owned group document."""

    __tablename__ = "gc_common_documents"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            name="uq_gc_common_doc_scope",
        ),
        UniqueConstraint("storage_key", name="uq_gc_common_doc_storage_key"),
        UniqueConstraint(
            "gc_group_access_id",
            "logical_document_id",
            "version",
            name="uq_gc_common_doc_logical_version",
        ),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_gc_common_doc_access",
            ondelete="CASCADE",
        ),
        CheckConstraint("version >= 1", name="ck_gc_common_doc_version"),
        CheckConstraint("byte_size > 0", name="ck_gc_common_doc_size"),
        CheckConstraint(
            "length(checksum_sha256) = 64",
            name="ck_gc_common_doc_checksum",
        ),
        CheckConstraint(
            "category IN ('itinerary_pdf', 'travel_tips', 'common_instructions', "
            "'destination', 'emergency', 'hotel', 'flight_summary', 'meeting_point', "
            "'dress_code', 'baggage', 'other')",
            name="ck_gc_common_doc_category",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'retired', 'revoked')",
            name="ck_gc_common_doc_status",
        ),
        CheckConstraint(
            "availability_expires_at IS NULL OR availability_starts_at IS NULL "
            "OR availability_expires_at > availability_starts_at",
            name="ck_gc_common_doc_window",
        ),
        CheckConstraint(
            "(status = 'draft' AND published_at IS NULL) OR "
            "(status IN ('published', 'retired', 'revoked') AND published_at IS NOT NULL)",
            name="ck_gc_common_doc_publish_shape",
        ),
        CheckConstraint(
            "status != 'published' OR "
            "(passenger_visible OR client_manager_visible OR coordinator_visible)",
            name="ck_gc_common_doc_audience",
        ),
        Index(
            "uq_gc_common_doc_published",
            "gc_group_access_id",
            "logical_document_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
            sqlite_where=text("status = 'published'"),
        ),
        Index(
            "ix_gc_common_doc_manifest",
            "gc_group_access_id",
            "status",
            "sort_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    logical_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    passenger_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    client_manager_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    coordinator_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    offline_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    availability_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    availability_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GCItineraryVersionModel(Base):
    """A complete immutable itinerary snapshot with draft/publish lifecycle."""

    __tablename__ = "gc_itinerary_versions"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            name="uq_gc_itinerary_version_scope",
        ),
        UniqueConstraint("gc_group_access_id", "version", name="uq_gc_itinerary_version_number"),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_gc_itinerary_version_access",
            ondelete="CASCADE",
        ),
        CheckConstraint("version >= 1", name="ck_gc_itinerary_version_number"),
        CheckConstraint("revision >= 1", name="ck_gc_itinerary_version_revision"),
        CheckConstraint(
            "status IN ('draft', 'published', 'retired')",
            name="ck_gc_itinerary_version_status",
        ),
        CheckConstraint(
            "availability_expires_at IS NULL OR availability_starts_at IS NULL "
            "OR availability_expires_at > availability_starts_at",
            name="ck_gc_itinerary_version_window",
        ),
        CheckConstraint(
            "(status = 'draft' AND published_at IS NULL) OR "
            "(status IN ('published', 'retired') AND published_at IS NOT NULL)",
            name="ck_gc_itinerary_publish_shape",
        ),
        CheckConstraint(
            "content_checksum IS NULL OR length(content_checksum) = 64",
            name="ck_gc_itinerary_checksum",
        ),
        CheckConstraint(
            "status = 'draft' OR content_checksum IS NOT NULL",
            name="ck_gc_itinerary_published_checksum",
        ),
        Index(
            "uq_gc_itinerary_published",
            "gc_group_access_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
            sqlite_where=text("status = 'published'"),
        ),
        Index(
            "ix_gc_itinerary_access_status",
            "gc_group_access_id",
            "status",
            "version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    destination_information: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    availability_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    availability_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GCItineraryDayModel(Base):
    """One ordered day within a versioned structured itinerary."""

    __tablename__ = "gc_itinerary_days"
    __table_args__ = (
        UniqueConstraint(
            "itinerary_version_id",
            "day_number",
            name="uq_gc_itinerary_day_number",
        ),
        UniqueConstraint(
            "id",
            "itinerary_version_id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            name="uq_gc_itinerary_day_scope",
        ),
        ForeignKeyConstraint(
            [
                "itinerary_version_id",
                "gc_group_access_id",
                "agency_id",
                "group_id",
            ],
            [
                "gc_itinerary_versions.id",
                "gc_itinerary_versions.gc_group_access_id",
                "gc_itinerary_versions.agency_id",
                "gc_itinerary_versions.group_id",
            ],
            name="fk_gc_itinerary_day_version",
            ondelete="CASCADE",
        ),
        CheckConstraint("day_number >= 1", name="ck_gc_itinerary_day_number"),
        CheckConstraint("sort_order >= 0", name="ck_gc_itinerary_day_sort"),
        Index(
            "ix_gc_itinerary_day_order",
            "itinerary_version_id",
            "sort_order",
            "day_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    itinerary_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    day_number: Mapped[int] = mapped_column(Integer, nullable=False)
    trip_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GCItineraryItemModel(Base):
    """A bounded, typed schedule item suitable for compact mobile manifests."""

    __tablename__ = "gc_itinerary_items"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "itinerary_day_id",
                "itinerary_version_id",
                "gc_group_access_id",
                "agency_id",
                "group_id",
            ],
            [
                "gc_itinerary_days.id",
                "gc_itinerary_days.itinerary_version_id",
                "gc_itinerary_days.gc_group_access_id",
                "gc_itinerary_days.agency_id",
                "gc_itinerary_days.group_id",
            ],
            name="fk_gc_itinerary_item_day",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["common_document_id", "gc_group_access_id", "agency_id", "group_id"],
            [
                "gc_common_documents.id",
                "gc_common_documents.gc_group_access_id",
                "gc_common_documents.agency_id",
                "gc_common_documents.group_id",
            ],
            name="fk_gc_itinerary_item_document",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "item_type IN ('travel', 'flight', 'transfer', 'hotel', 'meal', 'meeting', "
            "'activity', 'conference', 'free_time', 'instruction', 'other')",
            name="ck_gc_itinerary_item_type",
        ),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at >= starts_at",
            name="ck_gc_itinerary_item_window",
        ),
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="ck_gc_itinerary_item_latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="ck_gc_itinerary_item_longitude",
        ),
        CheckConstraint("sort_order >= 0", name="ck_gc_itinerary_item_sort"),
        Index("ix_gc_itinerary_item_order", "itinerary_day_id", "sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    itinerary_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    itinerary_day_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    common_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    item_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="activity", server_default="activity"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_all_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    location_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_address: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    map_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_important: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    public_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class GCAnnouncementModel(Base):
    """A versioned, role-targeted group update safe for offline display."""

    __tablename__ = "gc_announcements"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            name="uq_gc_announcement_scope",
        ),
        UniqueConstraint(
            "gc_group_access_id",
            "logical_announcement_id",
            "version",
            name="uq_gc_announcement_logical_version",
        ),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_gc_announcement_access",
            ondelete="CASCADE",
        ),
        CheckConstraint("version >= 1", name="ck_gc_announcement_version"),
        CheckConstraint(
            "category IN ('general', 'itinerary', 'room', 'flight', 'document', "
            "'coordinator', 'emergency', 'sync')",
            name="ck_gc_announcement_category",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'emergency')",
            name="ck_gc_announcement_priority",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'retired', 'revoked')",
            name="ck_gc_announcement_status",
        ),
        CheckConstraint(
            "availability_expires_at IS NULL OR availability_starts_at IS NULL "
            "OR availability_expires_at > availability_starts_at",
            name="ck_gc_announcement_window",
        ),
        CheckConstraint(
            "(status = 'draft' AND published_at IS NULL) OR "
            "(status IN ('published', 'retired', 'revoked') AND published_at IS NOT NULL)",
            name="ck_gc_announcement_publish_shape",
        ),
        CheckConstraint(
            "status != 'published' OR "
            "(passenger_visible OR client_manager_visible OR coordinator_visible)",
            name="ck_gc_announcement_audience",
        ),
        Index(
            "uq_gc_announcement_published",
            "gc_group_access_id",
            "logical_announcement_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
            sqlite_where=text("status = 'published'"),
        ),
        Index(
            "ix_gc_announcement_feed",
            "gc_group_access_id",
            "status",
            "published_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    logical_announcement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(
        String(24), nullable=False, default="general", server_default="general"
    )
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", server_default="normal"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    deep_link_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    passenger_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    client_manager_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    coordinator_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    offline_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    availability_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    availability_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MobilePassengerIdentityModel(Base):
    """A staff-approved passenger-to-phone binding for exactly one enabled trip."""

    __tablename__ = "mobile_passenger_identities"
    __table_args__ = (
        UniqueConstraint(
            "gc_group_access_id",
            "passenger_submission_id",
            name="uq_mobile_passenger_identity_passenger",
        ),
        UniqueConstraint("id", "agency_id", name="uq_mobile_passenger_identity_agency"),
        UniqueConstraint(
            "id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            name="uq_mobile_passenger_identity_scope",
        ),
        UniqueConstraint(
            "id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            "passenger_submission_id",
            name="uq_mobile_passenger_identity_document_scope",
        ),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_passenger_identity_access",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["passenger_submission_id", "agency_id", "group_id"],
            ["passport_submissions.id", "passport_submissions.agency_id", "passport_submissions.group_id"],
            name="fk_mobile_passenger_identity_submission_scope",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('pending', 'eligible', 'claimed', 'suspended', 'revoked')",
            name="ck_mobile_passenger_identity_status",
        ),
        CheckConstraint(
            "length(normalized_phone_number) BETWEEN 9 AND 16 "
            "AND normalized_phone_number LIKE '+%'",
            name="ck_mobile_passenger_identity_phone",
        ),
        CheckConstraint(
            "length(phone_lookup_hash) = 64",
            name="ck_mobile_passenger_identity_phone_hash",
        ),
        CheckConstraint(
            "claim_generation >= 0",
            name="ck_mobile_passenger_identity_generation",
        ),
        CheckConstraint(
            "NOT is_shared_number OR "
            "(requires_secondary_verification AND secondary_factor_type IS NOT NULL "
            "AND secondary_factor_hash IS NOT NULL)",
            name="ck_mobile_passenger_identity_shared",
        ),
        CheckConstraint(
            "(secondary_factor_type IS NULL) = (secondary_factor_hash IS NULL)",
            name="ck_mobile_passenger_identity_factor_pair",
        ),
        CheckConstraint(
            "secondary_factor_type IS NULL OR secondary_factor_type IN "
            "('passenger_identifier', 'employee_code', 'date_of_birth', "
            "'booking_code', 'invitation_token')",
            name="ck_mobile_passenger_identity_factor_type",
        ),
        CheckConstraint(
            "(status = 'claimed' AND claimed_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status IN ('pending', 'eligible') AND claimed_at IS NULL "
            "AND revoked_at IS NULL) OR "
            "(status = 'suspended' AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL)",
            name="ck_mobile_passenger_identity_state_shape",
        ),
        Index(
            "ix_mobile_passenger_phone_status",
            "phone_lookup_hash",
            "status",
        ),
        Index(
            "ix_mobile_passenger_group_status",
            "gc_group_access_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passenger_submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    normalized_phone_number: Mapped[str] = mapped_column(String(16), nullable=False)
    phone_lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    is_shared_number: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    requires_secondary_verification: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    secondary_factor_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    secondary_factor_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claim_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MobileDocumentMetadataCacheModel(Base):
    """Derived integrity metadata for an authoritative personal document.

    The object and ownership remain in the existing passport/distribution
    tables.  This projection stores only the bounded metadata needed to decide
    whether a device must download a new encrypted offline copy.
    """

    __tablename__ = "mobile_document_metadata_cache"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "source_kind",
            "source_id",
            name="uq_mobile_document_cache_source",
        ),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_document_cache_access",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            [
                "passenger_identity_id",
                "gc_group_access_id",
                "agency_id",
                "group_id",
                "passenger_submission_id",
            ],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
                "mobile_passenger_identities.passenger_submission_id",
            ],
            name="fk_mobile_document_cache_identity",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "source_kind IN ('passport_front', 'passport_back', 'distributed')",
            name="ck_mobile_document_cache_source_kind",
        ),
        CheckConstraint(
            "content_type IN ('application/pdf', 'image/jpeg', 'image/png', 'image/webp')",
            name="ck_mobile_document_cache_content_type",
        ),
        CheckConstraint(
            "byte_size > 0 AND byte_size <= 104857600",
            name="ck_mobile_document_cache_size",
        ),
        CheckConstraint(
            "length(storage_key_hash) = 64 AND length(checksum_sha256) = 64",
            name="ck_mobile_document_cache_hashes",
        ),
        CheckConstraint("version >= 1", name="ck_mobile_document_cache_version"),
        Index(
            "ix_mobile_document_cache_identity",
            "passenger_identity_id",
            "updated_at",
        ),
        Index(
            "ix_mobile_document_cache_access",
            "gc_group_access_id",
            "updated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passenger_identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passenger_submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    storage_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MobileOTPChallengeModel(Base):
    """Short-lived OTP state containing hashes only and neutral subject pointers."""

    __tablename__ = "mobile_otp_challenges"
    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('passenger', 'client_manager', 'coordinator')",
            name="ck_mobile_otp_subject_type",
        ),
        CheckConstraint(
            "purpose IN ('login', 'activation', 'step_up')",
            name="ck_mobile_otp_purpose",
        ),
        CheckConstraint(
            "status IN ('pending', 'verified', 'consumed', 'expired', 'locked', 'cancelled')",
            name="ck_mobile_otp_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20 "
            "AND attempt_count <= max_attempts",
            name="ck_mobile_otp_attempts",
        ),
        CheckConstraint(
            "resend_count >= 0 AND max_resends BETWEEN 0 AND 20 AND resend_count <= max_resends",
            name="ck_mobile_otp_resends",
        ),
        CheckConstraint("expires_at > created_at", name="ck_mobile_otp_expiry"),
        CheckConstraint(
            "length(phone_lookup_hash) = 64 AND length(challenge_token_hash) = 64",
            name="ck_mobile_otp_lookup_hashes",
        ),
        CheckConstraint(
            "NOT (passenger_identity_id IS NOT NULL AND user_id IS NOT NULL)",
            name="ck_mobile_otp_single_subject",
        ),
        CheckConstraint(
            "(status IN ('verified', 'consumed') AND verified_at IS NOT NULL) OR "
            "(status NOT IN ('verified', 'consumed') AND verified_at IS NULL)",
            name="ck_mobile_otp_verified_shape",
        ),
        CheckConstraint(
            "(status = 'consumed' AND consumed_at IS NOT NULL) OR "
            "(status != 'consumed' AND consumed_at IS NULL)",
            name="ck_mobile_otp_consumed_shape",
        ),
        Index("ix_mobile_otp_phone_created", "phone_lookup_hash", "created_at"),
        Index("ix_mobile_otp_expiry_status", "status", "expires_at"),
        Index(
            "uq_mobile_otp_pending_phone",
            "phone_lookup_hash",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True
    )
    passenger_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mobile_passenger_identities.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    subject_type: Mapped[str] = mapped_column(String(24), nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(16), nullable=False, default="login", server_default="login"
    )
    phone_lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    challenge_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    resend_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_resends: Mapped[int] = mapped_column(Integer, nullable=False)
    resend_available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MobileDeviceSessionModel(Base):
    """Revocable mobile session bound to one installation and token family."""

    __tablename__ = "mobile_device_sessions"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", name="uq_mobile_session_agency"),
        UniqueConstraint(
            "id",
            "agency_id",
            "refresh_family_id",
            name="uq_mobile_session_refresh_family",
        ),
        ForeignKeyConstraint(
            ["passenger_identity_id", "agency_id"],
            ["mobile_passenger_identities.id", "mobile_passenger_identities.agency_id"],
            name="fk_mobile_session_passenger",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["selected_gc_group_access_id", "agency_id", "selected_group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_session_selected_group",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "subject_role IN ('passenger', 'client_manager', 'coordinator')",
            name="ck_mobile_session_subject_role",
        ),
        CheckConstraint(
            "platform IN ('android', 'ios')",
            name="ck_mobile_session_platform",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked', 'expired')",
            name="ck_mobile_session_status",
        ),
        CheckConstraint(
            "session_generation >= 0",
            name="ck_mobile_session_generation",
        ),
        CheckConstraint(
            "length(device_identifier_hash) = 64",
            name="ck_mobile_session_device_hash",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_mobile_session_expiry",
        ),
        CheckConstraint(
            "(subject_role = 'passenger' AND user_id IS NULL "
            "AND passenger_subject_hash IS NOT NULL) OR "
            "(subject_role IN ('client_manager', 'coordinator') "
            "AND user_id IS NOT NULL AND passenger_identity_id IS NULL "
            "AND passenger_subject_hash IS NULL)",
            name="ck_mobile_session_subject_shape",
        ),
        CheckConstraint(
            "passenger_identity_id IS NULL OR subject_role = 'passenger'",
            name="ck_mobile_session_passenger_role",
        ),
        CheckConstraint(
            "(selected_gc_group_access_id IS NULL) = (selected_group_id IS NULL)",
            name="ck_mobile_session_selected_group_pair",
        ),
        CheckConstraint(
            "(status = 'active' AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL) OR "
            "status = 'expired'",
            name="ck_mobile_session_state_shape",
        ),
        Index(
            "uq_mobile_session_user_device_active",
            "user_id",
            "device_identifier_hash",
            unique=True,
            postgresql_where=text("status = 'active' AND user_id IS NOT NULL"),
            sqlite_where=text("status = 'active' AND user_id IS NOT NULL"),
        ),
        Index(
            "uq_mobile_session_passenger_device_active",
            "passenger_subject_hash",
            "device_identifier_hash",
            unique=True,
            postgresql_where=text("status = 'active' AND passenger_subject_hash IS NOT NULL"),
            sqlite_where=text("status = 'active' AND passenger_subject_hash IS NOT NULL"),
        ),
        Index("ix_mobile_session_expiry", "status", "expires_at"),
        Index("ix_mobile_session_agency_seen", "agency_id", "last_seen_at"),
        Index("ix_mobile_session_account", "agency_id", "account_id"),
        Index(
            "ix_mobile_session_group_status_expiry",
            "agency_id",
            "selected_gc_group_access_id",
            "status",
            "expires_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    subject_role: Mapped[str] = mapped_column(String(24), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    # Stable client-side cache/account namespace. Passenger identity_id changes
    # when the same verified account switches trips; account_id deliberately
    # does not. For newly issued single-trip and staff sessions it equals the
    # initial principal id, preserving existing device cache namespaces.
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passenger_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    passenger_subject_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_gc_group_access_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    selected_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    device_identifier_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    app_version: Mapped[str] = mapped_column(String(32), nullable=False)
    device_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    session_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    refresh_family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    created_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set only after the device commits a complete, version-matched trip sync
    # and acknowledges it through /mobile/sync/ack.  Keeping this distinct
    # from last_seen_at prevents ordinary authentication/refresh traffic from
    # being reported as a successfully synchronized device.
    last_sync_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MobilePassengerSessionIdentityModel(Base):
    """An exact passenger identity proven for one revocable device session.

    A passenger access token still names exactly one selected identity.  These
    rows only retain the bounded set that the same OTP/secondary-factor proof
    authorized, allowing a later trip switch without repeating OTP while
    preserving tenant, group, and identity ownership at the database layer.
    """

    __tablename__ = "mobile_passenger_session_identities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "agency_id"],
            ["mobile_device_sessions.id", "mobile_device_sessions.agency_id"],
            name="fk_mobile_passenger_session_identity_session",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            [
                "passenger_identity_id",
                "gc_group_access_id",
                "agency_id",
                "group_id",
            ],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
            ],
            name="fk_mobile_passenger_session_identity_scope",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "identity_claim_generation >= 0",
            name="ck_mobile_passenger_session_identity_generation",
        ),
        Index(
            "ix_mobile_passenger_session_identity_group",
            "session_id",
            "group_id",
        ),
        Index(
            "ix_mobile_passenger_session_identity_identity",
            "passenger_identity_id",
            "session_id",
        ),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    passenger_identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    identity_claim_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    authorized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MobileRefreshTokenModel(Base):
    """A single-use, hash-only refresh token in a rotation family."""

    __tablename__ = "mobile_refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_mobile_refresh_token_hash"),
        UniqueConstraint(
            "session_id",
            "token_generation",
            name="uq_mobile_refresh_session_generation",
        ),
        UniqueConstraint(
            "id",
            "session_id",
            "agency_id",
            "family_id",
            name="uq_mobile_refresh_token_scope",
        ),
        ForeignKeyConstraint(
            ["session_id", "agency_id", "family_id"],
            [
                "mobile_device_sessions.id",
                "mobile_device_sessions.agency_id",
                "mobile_device_sessions.refresh_family_id",
            ],
            name="fk_mobile_refresh_session_family",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["parent_token_id", "session_id", "agency_id", "family_id"],
            [
                "mobile_refresh_tokens.id",
                "mobile_refresh_tokens.session_id",
                "mobile_refresh_tokens.agency_id",
                "mobile_refresh_tokens.family_id",
            ],
            name="fk_mobile_refresh_parent",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "length(token_hash) = 64",
            name="ck_mobile_refresh_token_hash",
        ),
        CheckConstraint(
            "token_generation >= 1",
            name="ck_mobile_refresh_generation",
        ),
        CheckConstraint("expires_at > issued_at", name="ck_mobile_refresh_expiry"),
        CheckConstraint(
            "(revoked_at IS NULL AND revoke_reason IS NULL) OR revoked_at IS NOT NULL",
            name="ck_mobile_refresh_revocation_shape",
        ),
        CheckConstraint(
            "reuse_detected_at IS NULL OR revoked_at IS NOT NULL",
            name="ck_mobile_refresh_reuse_shape",
        ),
        Index(
            "ix_mobile_refresh_active",
            "session_id",
            "expires_at",
            postgresql_where=text("consumed_at IS NULL AND revoked_at IS NULL"),
            sqlite_where=text("consumed_at IS NULL AND revoked_at IS NULL"),
        ),
        Index("ix_mobile_refresh_family", "family_id", "token_generation"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parent_token_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reuse_detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MobilePushRegistrationModel(Base):
    """Application-encrypted APNs/FCM token bound to a revocable session."""

    __tablename__ = "mobile_push_registrations"
    __table_args__ = (
        UniqueConstraint("provider", "token_lookup_hash", name="uq_mobile_push_provider_token"),
        ForeignKeyConstraint(
            ["session_id", "agency_id"],
            ["mobile_device_sessions.id", "mobile_device_sessions.agency_id"],
            name="fk_mobile_push_session",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "provider IN ('expo', 'fcm', 'apns')",
            name="ck_mobile_push_provider",
        ),
        CheckConstraint("platform IN ('android', 'ios')", name="ck_mobile_push_platform"),
        CheckConstraint(
            "environment IN ('development', 'production')",
            name="ck_mobile_push_environment",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled', 'revoked')",
            name="ck_mobile_push_status",
        ),
        CheckConstraint("token_key_version >= 1", name="ck_mobile_push_key_version"),
        CheckConstraint(
            "length(token_ciphertext) > 0 AND length(token_lookup_hash) = 64",
            name="ck_mobile_push_token_material",
        ),
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL) OR "
            "(status != 'revoked' AND revoked_at IS NULL)",
            name="ck_mobile_push_revoked_shape",
        ),
        Index("ix_mobile_push_session_status", "session_id", "status"),
        Index("ix_mobile_push_failure", "status", "last_failure_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    app_bundle_id: Mapped[str] = mapped_column(String(255), nullable=False)
    token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    token_lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    notifications_authorized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    last_registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MobilePushDeliveryModel(Base):
    """Durable provider ticket and receipt state for one device delivery."""

    __tablename__ = "mobile_push_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "notification_id",
            "registration_id",
            name="uq_mobile_push_delivery_target",
        ),
        CheckConstraint(
            "provider IN ('expo', 'fcm', 'apns')",
            name="ck_mobile_push_delivery_provider",
        ),
        CheckConstraint(
            "status IN ('submitting', 'retry', 'receipt_pending', 'delivered', "
            "'failed', 'cancelled')",
            name="ck_mobile_push_delivery_status",
        ),
        CheckConstraint(
            "send_attempts >= 0 AND receipt_attempts >= 0",
            name="ck_mobile_push_delivery_attempts",
        ),
        CheckConstraint(
            "(provider_ticket_id IS NULL AND submitted_at IS NULL) OR "
            "(provider_ticket_id IS NOT NULL AND submitted_at IS NOT NULL)",
            name="ck_mobile_push_delivery_ticket_shape",
        ),
        CheckConstraint(
            "status NOT IN ('receipt_pending', 'delivered') OR "
            "provider_ticket_id IS NOT NULL",
            name="ck_mobile_push_delivery_receipt_shape",
        ),
        CheckConstraint(
            "(status = 'delivered' AND delivered_at IS NOT NULL) OR "
            "(status != 'delivered' AND delivered_at IS NULL)",
            name="ck_mobile_push_delivery_delivered_shape",
        ),
        CheckConstraint(
            "(status = 'failed' AND failed_at IS NOT NULL) OR "
            "(status != 'failed' AND failed_at IS NULL)",
            name="ck_mobile_push_delivery_failed_shape",
        ),
        Index(
            "uq_mobile_push_delivery_provider_ticket",
            "provider",
            "provider_ticket_id",
            unique=True,
            postgresql_where=text("provider_ticket_id IS NOT NULL"),
            sqlite_where=text("provider_ticket_id IS NOT NULL"),
        ),
        Index(
            "ix_mobile_push_delivery_due",
            "provider",
            "status",
            "next_attempt_at",
        ),
        Index("ix_mobile_push_delivery_notification", "notification_id", "status"),
        Index("ix_mobile_push_delivery_registration", "registration_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mobile_notifications.id", ondelete="CASCADE"),
        nullable=False,
    )
    registration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mobile_push_registrations.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_ticket_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="submitting", server_default="submitting"
    )
    send_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    receipt_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MobileNotificationModel(Base):
    """Per-recipient notification and read state with lock-screen-safe content."""

    __tablename__ = "mobile_notifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_notification_access",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "recipient_type IN ('passenger', 'client_manager', 'coordinator')",
            name="ck_mobile_notification_recipient_type",
        ),
        CheckConstraint(
            "(recipient_type = 'passenger' AND recipient_passenger_identity_id IS NOT NULL "
            "AND recipient_user_id IS NULL) OR "
            "(recipient_type IN ('client_manager', 'coordinator') "
            "AND recipient_user_id IS NOT NULL "
            "AND recipient_passenger_identity_id IS NULL)",
            name="ck_mobile_notification_recipient_shape",
        ),
        CheckConstraint(
            "category IN ('announcement', 'itinerary', 'room', 'flight', 'document', "
            "'coordinator', 'emergency', 'security', 'sync')",
            name="ck_mobile_notification_category",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'emergency')",
            name="ck_mobile_notification_priority",
        ),
        CheckConstraint(
            "status IN ('queued', 'sent', 'failed', 'cancelled')",
            name="ck_mobile_notification_status",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > available_at",
            name="ck_mobile_notification_expiry",
        ),
        CheckConstraint(
            "(gc_group_access_id IS NULL) = (group_id IS NULL)",
            name="ck_mobile_notification_group_pair",
        ),
        CheckConstraint(
            "NOT contains_sensitive_content OR lock_screen_body IS NULL",
            name="ck_mobile_notification_lock_screen_privacy",
        ),
        Index(
            "uq_mobile_notification_user_dedupe",
            "recipient_user_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("recipient_user_id IS NOT NULL"),
            sqlite_where=text("recipient_user_id IS NOT NULL"),
        ),
        Index(
            "uq_mobile_notification_passenger_dedupe",
            "recipient_passenger_identity_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("recipient_passenger_identity_id IS NOT NULL"),
            sqlite_where=text("recipient_passenger_identity_id IS NOT NULL"),
        ),
        Index(
            "ix_mobile_notification_user_feed",
            "recipient_user_id",
            "read_at",
            "created_at",
        ),
        Index(
            "ix_mobile_notification_passenger_feed",
            "recipient_passenger_identity_id",
            "read_at",
            "created_at",
        ),
        Index("ix_mobile_notification_delivery", "status", "available_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    gc_group_access_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    recipient_type: Mapped[str] = mapped_column(String(24), nullable=False)
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    recipient_passenger_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mobile_passenger_identities.id", ondelete="CASCADE"),
        nullable=True,
    )
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", server_default="normal"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    lock_screen_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lock_screen_body: Mapped[str | None] = mapped_column(String(240), nullable=True)
    contains_sensitive_content: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    deep_link_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    public_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MobileSyncChangeModel(Base):
    """Monotonic compact change feed; file bodies and secrets are never embedded."""

    __tablename__ = "mobile_sync_changes"
    __table_args__ = (
        UniqueConstraint("id", name="uq_mobile_sync_change_id"),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_sync_change_access",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["passenger_identity_id", "gc_group_access_id", "agency_id", "group_id"],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
            ],
            name="fk_mobile_sync_change_passenger",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "audience IN ('all', 'passenger', 'client_manager', 'coordinator')",
            name="ck_mobile_sync_change_audience",
        ),
        CheckConstraint(
            "operation IN ('upsert', 'delete', 'revoke', 'publish')",
            name="ck_mobile_sync_change_operation",
        ),
        CheckConstraint("version >= 1", name="ck_mobile_sync_change_version"),
        CheckConstraint(
            "access_generation >= 0",
            name="ck_mobile_sync_change_generation",
        ),
        CheckConstraint(
            "payload_checksum IS NULL OR length(payload_checksum) = 64",
            name="ck_mobile_sync_change_checksum",
        ),
        CheckConstraint(
            "passenger_identity_id IS NULL OR audience = 'passenger'",
            name="ck_mobile_sync_change_passenger_audience",
        ),
        Index("ix_mobile_sync_change_agency_cursor", "agency_id", "sequence"),
        Index("ix_mobile_sync_change_group_cursor", "gc_group_access_id", "sequence"),
        Index(
            "ix_mobile_sync_change_passenger_cursor",
            "passenger_identity_id",
            "sequence",
        ),
        Index("ix_mobile_sync_change_expiry", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    sequence: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(always=False),
        primary_key=True,
        autoincrement=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passenger_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    audience: Mapped[str] = mapped_column(
        String(24), nullable=False, default="all", server_default="all"
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    access_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    payload_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PassengerFamilyDelegationModel(Base):
    """Explicit, revocable dependent grant; disabled by default and never inferred."""

    __tablename__ = "passenger_family_delegations"
    __table_args__ = (
        UniqueConstraint(
            "lead_identity_id",
            "dependent_identity_id",
            name="uq_passenger_family_delegation_pair",
        ),
        ForeignKeyConstraint(
            ["lead_identity_id", "gc_group_access_id", "agency_id", "group_id"],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
            ],
            name="fk_passenger_family_lead",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["dependent_identity_id", "gc_group_access_id", "agency_id", "group_id"],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
            ],
            name="fk_passenger_family_dependent",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "lead_identity_id != dependent_identity_id",
            name="ck_passenger_family_not_self",
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'revoked', 'expired')",
            name="ck_passenger_family_status",
        ),
        CheckConstraint(
            "NOT is_enabled OR status = 'active'",
            name="ck_passenger_family_enabled_status",
        ),
        CheckConstraint(
            "expires_at IS NULL OR effective_at IS NULL OR expires_at > effective_at",
            name="ck_passenger_family_window",
        ),
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL) OR "
            "(status != 'revoked' AND revoked_at IS NULL)",
            name="ck_passenger_family_revoked_shape",
        ),
        Index("ix_passenger_family_lead_status", "lead_identity_id", "status"),
        Index(
            "ix_passenger_family_dependent_status",
            "dependent_identity_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    lead_identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dependent_identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    can_view_trip_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    can_view_documents: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    can_view_qr: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MobileIdempotencyReceiptModel(Base):
    """Durable result of one offline mutation, keyed within a device session."""

    __tablename__ = "mobile_idempotency_receipts"
    __table_args__ = (
        UniqueConstraint("session_id", "idempotency_key", name="uq_mobile_idempotency_session_key"),
        ForeignKeyConstraint(
            ["session_id", "agency_id"],
            ["mobile_device_sessions.id", "mobile_device_sessions.agency_id"],
            name="fk_mobile_idempotency_session",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_idempotency_access",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed', 'conflict')",
            name="ck_mobile_idempotency_status",
        ),
        CheckConstraint(
            "length(request_hash) = 64",
            name="ck_mobile_idempotency_request_hash",
        ),
        CheckConstraint(
            "response_hash IS NULL OR length(response_hash) = 64",
            name="ck_mobile_idempotency_response_hash",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_mobile_idempotency_expiry",
        ),
        CheckConstraint(
            "(gc_group_access_id IS NULL) = (group_id IS NULL)",
            name="ck_mobile_idempotency_group_pair",
        ),
        CheckConstraint(
            "(status = 'processing' AND completed_at IS NULL) OR "
            "(status != 'processing' AND completed_at IS NOT NULL)",
            name="ck_mobile_idempotency_completion",
        ),
        Index("ix_mobile_idempotency_expiry", "expires_at"),
        Index("ix_mobile_idempotency_status", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    gc_group_access_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="processing", server_default="processing"
    )
    response_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MobileIncidentModel(Base):
    """Coordinator incident created online or from the durable offline queue."""

    __tablename__ = "mobile_incidents"
    __table_args__ = (
        UniqueConstraint(
            "created_by_session_id",
            "client_event_id",
            name="uq_mobile_incident_session_event",
        ),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_incident_access",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["created_by_session_id", "agency_id"],
            ["mobile_device_sessions.id", "mobile_device_sessions.agency_id"],
            name="fk_mobile_incident_session",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "incident_type IN ('missing_passenger', 'medical', 'safety', 'transport', "
            "'hotel', 'document', 'meal', 'other')",
            name="ck_mobile_incident_type",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_mobile_incident_severity",
        ),
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved', 'closed')",
            name="ck_mobile_incident_status",
        ),
        CheckConstraint(
            "(status IN ('resolved', 'closed') AND resolved_at IS NOT NULL) OR "
            "(status IN ('open', 'acknowledged') AND resolved_at IS NULL)",
            name="ck_mobile_incident_resolution",
        ),
        Index(
            "ix_mobile_incident_group_status",
            "gc_group_access_id",
            "status",
            "occurred_at",
        ),
        Index("ix_mobile_incident_severity", "severity", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gc_group_access_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reported_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    affected_passenger_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mobile_passenger_identities.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    incident_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_confidential: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_offline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


__all__ = [
    "ClientManagerGroupAssignmentModel",
    "ClientManagerProfileModel",
    "ClientOrganizationModel",
    "GCAnnouncementModel",
    "GCCommonDocumentModel",
    "GCGroupAccessModel",
    "GCItineraryDayModel",
    "GCItineraryItemModel",
    "GCItineraryVersionModel",
    "MobileDeviceSessionModel",
    "MobileDocumentMetadataCacheModel",
    "MobileIdempotencyReceiptModel",
    "MobileIncidentModel",
    "MobileNotificationModel",
    "MobileOTPChallengeModel",
    "MobilePassengerIdentityModel",
    "MobilePassengerSessionIdentityModel",
    "MobilePushDeliveryModel",
    "MobilePushRegistrationModel",
    "MobileRefreshTokenModel",
    "MobileSyncChangeModel",
    "PassengerFamilyDelegationModel",
]
