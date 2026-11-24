"""Client group configuration, lifecycle and retained passport policy."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    literal_column,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.value_objects.custom_questions import (
    CustomDetailDefinition,
    CustomQuestionDefinition,
)
from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE
from app.infrastructure.database.model_base import JSONB, Base, _utcnow
from app.infrastructure.database.search_index_sql import GROUP_SEARCH_SQL

if TYPE_CHECKING:
    from app.infrastructure.database._core_models.broadcast_links import (
        ClientGroupWhatsAppBroadcastLinkModel,
    )
    from app.infrastructure.database._core_models.identity import AgencyModel
    from app.infrastructure.database._core_models.passport import PassportSubmissionModel
    from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel


class ClientGroupModel(Base):
    __module__ = "app.infrastructure.database.models"
    __tablename__ = "client_groups"
    banner_image_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    background_image_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    roster_revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    __table_args__ = (
        UniqueConstraint("id", "agency_id", "company_id", name="uq_client_groups_company_scope"),
        ForeignKeyConstraint(
            ["company_id", "agency_id"], ["client_organizations.id", "client_organizations.agency_id"],
            name="fk_client_groups_company_scope", ondelete="RESTRICT",
        ),
        Index("ix_client_groups_company_lifecycle", "agency_id", "company_id", "status", "created_at", "id"),
        Index("ix_client_groups_company_seek", "agency_id", "company_id", "created_at", "id"),

        Index("ix_client_group_search_trgm", literal_column(GROUP_SEARCH_SQL).label("search_text"),
              postgresql_using="gin", postgresql_ops={"search_text": "gin_trgm_ops"}).ddl_if(dialect="postgresql"),
        UniqueConstraint(
            "id",
            "agency_id",
            name="uq_client_groups_id_agency",
        ),
        CheckConstraint(
            "passport_retention_days_applied IS NULL OR "
            "passport_retention_days_applied BETWEEN 1 AND 3650",
            name="ck_client_groups_passport_retention_days_applied",
        ),
        CheckConstraint(
            "length(timezone) BETWEEN 1 AND 64 AND timezone = trim(timezone)",
            name="ck_client_groups_timezone_shape",
        ),
        CheckConstraint(
            "(passport_legal_hold = false AND passport_legal_hold_reason IS NULL "
            "AND passport_legal_hold_set_at IS NULL "
            "AND passport_legal_hold_set_by_user_id IS NULL) OR "
            "(passport_legal_hold = true "
            "AND length(trim(passport_legal_hold_reason)) BETWEEN 3 AND 500 "
            "AND passport_legal_hold_set_at IS NOT NULL)",
            name="ck_client_groups_passport_legal_hold_shape",
        ),
        Index(
            "ix_client_groups_passport_retention_due",
            "passport_legal_hold",
            "passport_purge_at",
            "id",
        ),
        Index(
            "ix_client_groups_agency_status_created_at",
            "agency_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    company_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    company: Mapped["ClientOrganizationModel | None"] = relationship(
        "ClientOrganizationModel", lazy="selectin", viewonly=True,
        foreign_keys="[ClientGroupModel.company_id, ClientGroupModel.agency_id]",
    )
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
    import_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
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
    upload_configuration: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
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
    custom_questions: Mapped[list[CustomQuestionDefinition]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    custom_details: Mapped[list[CustomDetailDefinition]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_passport_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deletion_retained_records: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    passport_purge_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    passport_retention_days_applied: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    # Retired feature: preserve historical values/schema; no runtime hold policy.
    passport_legal_hold: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    passport_legal_hold_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    passport_legal_hold_set_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    passport_legal_hold_set_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    agency: Mapped[AgencyModel] = relationship("AgencyModel", back_populates="client_groups")
    submissions: Mapped[list[PassportSubmissionModel]] = relationship(
        "PassportSubmissionModel", back_populates="group",
        primaryjoin="and_(ClientGroupModel.id == PassportSubmissionModel.group_id, "
                    "ClientGroupModel.agency_id == PassportSubmissionModel.agency_id)",
    )
    whatsapp_broadcast_links: Mapped[list[ClientGroupWhatsAppBroadcastLinkModel]] = relationship(
        "ClientGroupWhatsAppBroadcastLinkModel",
        back_populates="client_group",
        cascade="all, delete-orphan",
    )
