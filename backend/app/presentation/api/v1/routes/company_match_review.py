"""Bounded staff-visible matching preview and explicit roster inclusion."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import (
    COMPANY_ADMIN_ROLES,
    require_company,
    visible_company_groups,
)
from app.application.mcp.read_cursor import MCPReadCursor
from app.application.travellers.match_resolution import resolve_match
from app.core.config.settings import Settings, get_settings
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.domain.entities.entities import User
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.traveller_reuse_models import (
    TravellerMatchCaseModel,
    TravellerReconciliationJobModel,
)
from app.infrastructure.security.traveller_reuse_crypto import (
    ReuseCryptoUnavailable,
    TravellerReuseCrypto,
)
from app.presentation.api.v1.routes.companies import _private_response
from app.presentation.api.v1.routes.traveller_admin import _require_visible_group
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter(dependencies=[Depends(_private_response), Depends(require_cookie_csrf)])


class MatchCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source_kind: str
    source_row_key: str
    status: str
    reason_code: str
    traveller_id: uuid.UUID | None
    revision: int


class MatchPreviewResponse(BaseModel):
    items: list[MatchCaseResponse]
    next_cursor: str | None
    counts: dict[str, int]
    latest_job_status: str | None
    processed_count: int
    expected_group_revision: int


class ResolveMatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    traveller_id: uuid.UUID
    expected_revision: int = Field(ge=1)
    expected_group_revision: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=500)
    evidence_reviewed: Literal[True]


@router.get("/{company_id}/groups/{group_id}/travellers/matching-preview", response_model=MatchPreviewResponse)
async def matching_preview(company_id: uuid.UUID, group_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    cursor: str | None = Query(default=None, max_length=2048), page_size: int = Query(default=25, ge=1, le=100),
    status: Literal["all", "provisional", "ambiguous", "conflicting", "unmatched", "resolved"] = "all",
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> MatchPreviewResponse:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    group_revision = await session.scalar(visible_company_groups(user, company.agency_id, company.id)
        .where(ClientGroupModel.id == group_id).with_only_columns(ClientGroupModel.company_revision))
    if group_revision is None:
        raise HTTPException(404, "Group unavailable")
    model = TravellerMatchCaseModel
    scope = [model.agency_id == company.agency_id, model.company_id == company_id, model.group_id == group_id]
    counts = {row[0]: int(row[1]) for row in (await session.execute(
        select(model.status, func.count()).where(*scope).group_by(model.status))).all()}
    codec = MCPReadCursor(settings.app_secret_key, "company-matches-v1")
    try:
        state = codec.read(cursor, {"actor": user.id, "agency": company.agency_id, "company": company.id,
            "group": group_id, "status": status})
        after = uuid.UUID(state["after_id"]) if state.get("after_id") else None
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, "Invalid matching preview cursor") from exc
    query = select(model).where(*scope, model.created_at <= datetime.fromisoformat(state["cutoff"]))
    if status != "all":
        query = query.where(model.status == status)
    if after is not None:
        query = query.where(model.id > after)
    rows = list((await session.scalars(query.order_by(model.id).limit(page_size + 1))).all())
    more, rows = len(rows) > page_size, rows[:page_size]
    job = await session.scalar(select(TravellerReconciliationJobModel).where(
        TravellerReconciliationJobModel.agency_id == company.agency_id,
        TravellerReconciliationJobModel.company_id == company_id, TravellerReconciliationJobModel.group_id == group_id,
    ).order_by(TravellerReconciliationJobModel.created_at.desc(), TravellerReconciliationJobModel.id.desc()).limit(1))
    return MatchPreviewResponse(items=[MatchCaseResponse.model_validate(row) for row in rows],
        next_cursor=codec.next(state, {"id": rows[-1].id, "created_at": rows[-1].created_at}) if more else None, counts=counts,
        latest_job_status=job.status if job else None, processed_count=job.processed_count if job else 0,
        expected_group_revision=group_revision)


@router.post("/{company_id}/groups/{group_id}/travellers/matches/{case_id}/resolve")
async def resolve_roster_match(company_id: uuid.UUID, group_id: uuid.UUID, case_id: uuid.UUID,
    body: ResolveMatchBody, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    await _require_visible_group(session, user, company, group_id)
    try:
        crypto = TravellerReuseCrypto(get_traveller_reuse_settings())
    except ReuseCryptoUnavailable as exc:
        raise HTTPException(503, "Retained traveller review is unavailable") from exc
    participation = await resolve_match(session, agency_id=company.agency_id, company_id=company.id,
        group_id=group_id, case_id=case_id, traveller_id=body.traveller_id, expected_revision=body.expected_revision,
        expected_group_revision=body.expected_group_revision, reason=body.reason, actor_id=user.id, crypto=crypto)
    return {"participation_id": str(participation.id), "status": participation.status}
