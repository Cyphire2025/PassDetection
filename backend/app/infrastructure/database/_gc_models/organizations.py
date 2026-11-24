"""Client company and manager profile persistence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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

from app.infrastructure.database.gc_mobile_models import _utcnow
from app.infrastructure.database.model_base import Base


class ClientOrganizationModel(Base):
    """One client/company inside an agency; never grants group access itself."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

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
        Index("ix_client_org_directory_seek", "agency_id", "status", "normalized_name", "id"),
        Index("ix_client_org_directory_all_seek", "agency_id", "normalized_name", "id"),
        Index(
            "ix_client_org_search_trgm",
            "normalized_name",
            postgresql_using="gin",
            postgresql_ops={"normalized_name": "gin_trgm_ops"},
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    logo_image_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    @property
    def logo_url(self) -> str | None:
        from app.infrastructure.storage.branding_urls import branding_image_url

        return branding_image_url("company-logo", self.id, self.agency_id, self.logo_image_key)

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

    __module__ = "app.infrastructure.database.gc_mobile_models"

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


# Preserve metadata on the one preexisting lazy descriptor getter.
_logo_url = vars(ClientOrganizationModel)["logo_url"]
assert isinstance(_logo_url, property)
assert _logo_url.fget is not None
_logo_url.fget.__module__ = "app.infrastructure.database.gc_mobile_models"
