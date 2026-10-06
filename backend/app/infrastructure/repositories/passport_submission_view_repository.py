"""Lightweight identity projection and page-only passport detail hydration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, User, UserRole
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)


@dataclass(frozen=True, slots=True)
class PassportViewProjection:
    id: uuid.UUID
    client_name: str
    client_email: str | None
    client_phone: str | None
    family_head_name: str | None
    family_head_email: str | None
    family_head_phone: str | None
    departure_city: str | None
    extracted_fields: dict[str, Any] | None
    confirmed_fields: dict[str, Any] | None
    post_submission_verification: dict[str, Any] | None
    overall_confidence: float | None
    status: str
    updated_at: datetime
    extraction_revision: int
    document_follow_up: bool = False
    staff_metadata: dict[str, Any] | None = None


class PassportSubmissionViewRepository:
    """Keep complete-group duplicate semantics without loading complete rows.

    Identity clustering must see the authorized group to preserve its cautious
    cross-row evidence rules. The projection contains only the fields used by
    that algorithm; staff metadata is fetched only when searching its custom
    fields. Raw OCR, image keys and other detail payloads are loaded only for
    the requested page. Shared computed indexes are bound
    to a database revision and principal; authorization is checked on each read.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def revision(self, *, group_id: uuid.UUID, user: User, include_deleted: bool) -> tuple[int, date | None] | None:
        statement = select(ClientGroupModel.roster_revision, ClientGroupModel.travel_date).where(
            ClientGroupModel.id == group_id, ClientGroupModel.agency_id == user.agency_id)
        if not include_deleted:
            statement = statement.where(ClientGroupModel.status.notin_(["archived", "deleted"]),
                                         ClientGroupModel.deleted_at.is_(None))
        if user.role == UserRole.AGENCY_COORDINATOR:
            # Passenger assignments independently authorize this existing route;
            # requiring a separate group assignment would hide permitted rows.
            visible_passport = AuthorizationPolicy.apply_passport_visibility_scope(
                select(PassportSubmissionModel.id).where(
                    PassportSubmissionModel.group_id == group_id,
                    PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
                ), user,
            ).correlate(None).exists()
            statement = statement.where(visible_passport)
        else:
            statement = AuthorizationPolicy.apply_group_visibility_scope(statement, user)
        row = (await self._session.execute(statement)).one_or_none()
        return (row[0], row[1]) if row is not None else None

    async def projection(
        self, *, group_id: uuid.UUID, user: User, include_deleted: bool,
        include_search_metadata: bool = False,
    ) -> list[PassportViewProjection]:
        fields = tuple(
            name for name in PassportViewProjection.__dataclass_fields__
            if name != "staff_metadata" or include_search_metadata
        )
        statement = (
            select(*(getattr(PassportSubmissionModel, name) for name in fields))
            .join(ClientGroupModel, ClientGroupModel.id == PassportSubmissionModel.group_id)
            .where(
                PassportSubmissionModel.group_id == group_id,
                PassportSubmissionModel.agency_id == user.agency_id,
                PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
            )
        )
        if not include_deleted:
            statement = statement.where(
                ClientGroupModel.status.notin_(["archived", "deleted"]),
                ClientGroupModel.deleted_at.is_(None),
            )
        statement = AuthorizationPolicy.apply_passport_visibility_scope(statement, user)
        result = await self._session.execute(statement)
        # SQLite drops timezone information; the stored convention is UTC.
        # Match the detail DTO's normalization so revision fences compare the
        # same instant on cached and freshly computed pages in every store.
        return [PassportViewProjection(**{**row, "updated_at": row["updated_at"].replace(tzinfo=UTC)
            if row["updated_at"].tzinfo is None else row["updated_at"]}) for row in result.mappings()]

    async def page_details(
        self,
        *,
        submission_ids: list[uuid.UUID],
        group_id: uuid.UUID,
        user: User,
        include_deleted: bool = False,
    ) -> dict[uuid.UUID, PassportSubmissionOutputDTO]:
        if not submission_ids:
            return {}
        statement = (
            select(PassportSubmissionModel)
            .join(ClientGroupModel, ClientGroupModel.id == PassportSubmissionModel.group_id)
            .where(
                PassportSubmissionModel.id.in_(submission_ids),
                PassportSubmissionModel.group_id == group_id,
                PassportSubmissionModel.agency_id == user.agency_id,
                PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
            )
        )
        if not include_deleted:
            statement = statement.where(
                ClientGroupModel.status.notin_(["archived", "deleted"]),
                ClientGroupModel.deleted_at.is_(None),
            )
        statement = AuthorizationPolicy.apply_passport_visibility_scope(statement, user)
        result = await self._session.execute(statement)
        return {
            model.id: passport_submission_output_from_entity(
                PassportSubmissionRepository._to_entity(model)
            )
            for model in result.scalars()
        }
