"""Explicit administration-only reviewed ownership changes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import COMPANY_ADMIN_ROLES, company_agency_scope
from app.application.companies.assignment import assign_group_company
from app.application.companies.reassignment import ReassignmentReview, reassignment_preview
from app.application.dtos.client_group_dtos import client_group_output_from_entity
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.api.v1.routes.companies import _private_response
from app.presentation.api.v1.schemas.client_group_schemas import ClientGroupResponse
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter(dependencies=[Depends(_private_response)])


class ReassignmentPreviewResponse(BaseModel):
    group_id: uuid.UUID
    source_company_id: uuid.UUID | None
    target_company_id: uuid.UUID
    expected_revision: int
    expected_roster_revision: int
    submission_records: int
    accepted_participations: int
    active_claims: int
    active_grants: int
    manager_conflict: bool
    can_reassign: bool


class ReassignmentConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=0)
    expected_roster_revision: int = Field(ge=0)
    reason: str = Field(min_length=10, max_length=500)


@router.get("/{company_id}/reassignments/{group_id}/preview", response_model=ReassignmentPreviewResponse)
async def preview_company_reassignment(
    company_id: uuid.UUID, group_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
) -> ReassignmentPreviewResponse:
    return ReassignmentPreviewResponse.model_validate(await reassignment_preview(
        session, user=user, agency_id=company_agency_scope(user, agency_id), group_id=group_id, company_id=company_id,
    ))


@router.post("/{company_id}/reassignments/{group_id}", response_model=ClientGroupResponse,
             dependencies=[Depends(require_cookie_csrf)])
async def confirm_company_reassignment(
    company_id: uuid.UUID, group_id: uuid.UUID, body: ReassignmentConfirmRequest,
    agency_id: uuid.UUID | None = None, user: User = Depends(require_role(COMPANY_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ClientGroupResponse:
    group = await assign_group_company(
        session, user=user, agency_id=company_agency_scope(user, agency_id), group_id=group_id,
        company_id=company_id, expected_revision=body.expected_revision,
        review=ReassignmentReview(body.expected_roster_revision, body.reason),
    )
    return ClientGroupResponse.model_validate(client_group_output_from_entity(ClientGroupRepository._to_entity(group)))
