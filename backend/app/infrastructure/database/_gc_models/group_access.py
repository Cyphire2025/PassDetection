"""Versioned group availability and explicit manager access grants."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.gc_mobile_models import _utcnow
from app.infrastructure.database.model_base import Base


class GCGroupAccessModel(Base):
    """Deny-by-default mobile availability and version state for one group."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "gc_group_access"
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "agency_id", "client_organization_id"],
            ["client_groups.id", "client_groups.agency_id", "client_groups.company_id"],
            name="fk_gc_group_canonical_company",
            deferrable=True,
            initially="DEFERRED",
        ),
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
            "removed_at IS NULL OR (NOT is_enabled AND revoked_at IS NOT NULL)",
            name="ck_gc_group_access_removed_disabled",
        ),
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
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "client_manager_group_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id", "agency_id"],
            ["client_manager_profiles.id", "client_manager_profiles.agency_id"],
            name="fk_client_manager_assignment_retained_profile",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_client_manager_assignment_retained_group",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "NOT is_active OR organization_id IS NOT NULL",
            name="ck_client_manager_assignment_active_organization",
        ),
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
        Index("ix_client_manager_assignment_company", "agency_id", "organization_id", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
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
