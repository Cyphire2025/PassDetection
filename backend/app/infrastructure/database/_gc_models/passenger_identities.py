"""Tenant-scoped passenger identities bound to trip contacts."""

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


class MobilePassengerIdentityModel(Base):
    """A staff-approved passenger-to-phone binding for exactly one enabled trip."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

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
            [
                "passport_submissions.id",
                "passport_submissions.agency_id",
                "passport_submissions.group_id",
            ],
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
