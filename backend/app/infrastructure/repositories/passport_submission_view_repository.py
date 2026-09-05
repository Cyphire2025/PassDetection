"""Lightweight identity projection and page-only passport detail hydration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, User
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


class PassportSubmissionViewRepository:
    """Keep complete-group duplicate semantics without loading complete rows.

    Identity clustering must see the authorized group to preserve its cautious
    cross-row evidence rules. The projection contains only the fields used by
    that algorithm; raw OCR, image keys, document metadata and review payloads
    are loaded only for the requested page. Nothing is cached across requests
    or users, so visibility and extraction revisions remain current.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def projection(
        self, *, group_id: uuid.UUID, user: User, include_deleted: bool
    ) -> list[PassportViewProjection]:
        fields = tuple(PassportViewProjection.__dataclass_fields__)
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
        return [PassportViewProjection(**row) for row in result.mappings()]

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
