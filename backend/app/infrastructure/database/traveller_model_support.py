"""Shared column and foreign-key contracts for company-scoped traveller records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import _utcnow


class TravellerRecord:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


def company_scope(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["company_id", "agency_id"],
        ["client_organizations.id", "client_organizations.agency_id"],
        name=f"fk_{name}_company_scope",
        ondelete="RESTRICT",
    )


def record_scope(name: str) -> UniqueConstraint:
    return UniqueConstraint("id", "agency_id", "company_id", name=f"uq_{name}_scope")


def traveller_scope(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["traveller_id", "agency_id", "company_id"],
        ["traveller_profiles.id", "traveller_profiles.agency_id", "traveller_profiles.company_id"],
        name=f"fk_{name}_traveller_scope",
        ondelete="RESTRICT",
    )


def passport_scope(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["passport_id", "traveller_id", "agency_id", "company_id"],
        [
            "traveller_passports.id",
            "traveller_passports.traveller_id",
            "traveller_passports.agency_id",
            "traveller_passports.company_id",
        ],
        name=f"fk_{name}_passport_scope",
        ondelete="RESTRICT",
    )


def document_scope(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["document_revision_id", "passport_id", "traveller_id", "agency_id", "company_id"],
        [
            "traveller_document_revisions.id",
            "traveller_document_revisions.passport_id",
            "traveller_document_revisions.traveller_id",
            "traveller_document_revisions.agency_id",
            "traveller_document_revisions.company_id",
        ],
        name=f"fk_{name}_document_scope",
        ondelete="RESTRICT",
    )


def group_scope(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["group_id", "agency_id"],
        ["client_groups.id", "client_groups.agency_id"],
        name=f"fk_{name}_group_scope",
        ondelete="RESTRICT",
    )
