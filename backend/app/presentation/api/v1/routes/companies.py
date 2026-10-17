"""Companies/Clients administration independent of GC App enablement."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import (
    COMPANY_ADMIN_ROLES,
    COMPANY_LOOKUP_ROLES,
    company_agency_scope,
    require_company,
    visible_company_groups,
)
from app.application.companies.directory import (
    create_company,
    delete_company,
    search_companies,
    update_company,
)
from app.application.companies.traveller_metrics import GroupTravellerCounts, group_traveller_counts
from app.application.mcp.read_cursor import MCPReadCursor
from app.core.config.settings import Settings, get_settings
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, User
from app.domain.exceptions.exceptions import ValidationError
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.search_expressions import group_search_fields, substring_predicate
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.traveller_reuse_models import (
    TravellerParticipationModel,
    TravellerReconciliationJobModel,
)
from app.presentation.api.v1.schemas.company_schemas import (
    CompanyCreateRequest,
    CompanyGroupPageResponse,
    CompanyGroupResponse,
    CompanyLookupPageResponse,
    CompanyLookupResponse,
    CompanyPageResponse,
    CompanyResponse,
    CompanySummaryResponse,
    CompanyUpdateRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf


def _private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(dependencies=[Depends(_private_response)])


@router.get("", response_model=CompanyPageResponse)
async def list_companies(
    search: str = Query(default="", max_length=120), status: Literal["active", "inactive", "all"] = "all",
    cursor: str | None = Query(default=None, max_length=2048), page_size: int = Query(default=50, ge=1, le=100),
    agency_id: uuid.UUID | None = None, user: User = Depends(require_role(COMPANY_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
) -> CompanyPageResponse:
    scope = company_agency_scope(user, agency_id)
    items, next_cursor, has_more = await search_companies(
        session, user=user, agency_id=scope, search=search, status=status, cursor=cursor,
        page_size=page_size, secret=settings.app_secret_key,
    )
    return CompanyPageResponse(items=[CompanyResponse.model_validate(item) for item in items],
                               next_cursor=next_cursor, has_more=has_more)


@router.get("/lookup", response_model=CompanyLookupPageResponse)
async def lookup_companies(
    search: str = Query(default="", max_length=120), cursor: str | None = Query(default=None, max_length=2048),
    page_size: int = Query(default=30, ge=1, le=100), agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_LOOKUP_ROLES)), session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> CompanyLookupPageResponse:
    scope = company_agency_scope(user, agency_id)
    items, next_cursor, has_more = await search_companies(
        session, user=user, agency_id=scope, search=search, status="active", cursor=cursor,
        page_size=page_size, secret=settings.app_secret_key,
    )
    return CompanyLookupPageResponse(items=[CompanyLookupResponse.model_validate(item) for item in items],
                                     next_cursor=next_cursor, has_more=has_more)


@router.post("", response_model=CompanyResponse, status_code=201, dependencies=[Depends(require_cookie_csrf)])
async def add_company(
    body: CompanyCreateRequest, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
) -> CompanyResponse:
    company = await create_company(session, user=user, agency_id=agency_id, **body.model_dump())
    return CompanyResponse.model_validate(company)


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
) -> CompanyResponse:
    return CompanyResponse.model_validate(await require_company(
        session, user=user, company_id=company_id, agency_id=agency_id,
    ))


@router.patch("/{company_id}", response_model=CompanyResponse, dependencies=[Depends(require_cookie_csrf)])
async def edit_company(
    company_id: uuid.UUID, body: CompanyUpdateRequest, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
) -> CompanyResponse:
    changes = body.model_dump(exclude_unset=True, exclude={"expected_revision"})
    if ("name" in changes and changes["name"] is None) or ("status" in changes and changes["status"] is None):
        raise ValidationError("Name and status cannot be null")
    if changes.get("external_reference") == "":
        changes["external_reference"] = None
    return CompanyResponse.model_validate(await update_company(
        session, user=user, company_id=company_id, agency_id=agency_id,
        expected_revision=body.expected_revision, changes=changes,
    ))


@router.delete("/{company_id}", status_code=204, dependencies=[Depends(require_cookie_csrf)])
async def remove_company(
    company_id: uuid.UUID, expected_revision: int = Query(ge=1), agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
) -> Response:
    await delete_company(session, user=user, company_id=company_id, agency_id=agency_id,
                         expected_revision=expected_revision)
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})


@router.get("/{company_id}/summary", response_model=CompanySummaryResponse)
async def company_summary(
    company_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
) -> CompanySummaryResponse:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    scope = visible_company_groups(user, company.agency_id, company.id).with_only_columns(
        ClientGroupModel.id, ClientGroupModel.status,
    ).subquery()
    counts = dict((await session.execute(select(scope.c.status, func.count()).group_by(scope.c.status))).all())
    qualifying = (
        TravellerParticipationModel.agency_id == company.agency_id,
        TravellerParticipationModel.company_id == company.id,
        TravellerParticipationModel.group_id.in_(select(scope.c.id)),
        TravellerParticipationModel.status == "accepted",
    )
    accepted = (await session.execute(select(
        func.count(TravellerParticipationModel.id),
        func.count(func.distinct(TravellerParticipationModel.traveller_id)),
    ).where(*qualifying))).one()
    resolved_source = select(TravellerParticipationModel.id).where(
        *qualifying,
        TravellerParticipationModel.source_submission_id == PassportSubmissionModel.id,
    ).correlate(PassportSubmissionModel).exists()
    unresolved = int(await session.scalar(select(func.count()).select_from(PassportSubmissionModel).where(
        PassportSubmissionModel.agency_id == company.agency_id,
        PassportSubmissionModel.group_id.in_(select(scope.c.id)),
        PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        ~resolved_source,
    )) or 0)
    unprocessed = bool(await session.scalar(select(TravellerReconciliationJobModel.id).where(
        TravellerReconciliationJobModel.agency_id == company.agency_id,
        TravellerReconciliationJobModel.company_id == company.id,
        TravellerReconciliationJobModel.group_id.in_(select(scope.c.id)),
        TravellerReconciliationJobModel.status.in_(("queued", "running", "failed")),
    ).limit(1)))
    return CompanySummaryResponse(active_groups=counts.get("active", 0), closed_groups=counts.get("closed", 0),
                                  archived_groups=counts.get("archived", 0), total_groups=sum(counts.values()),
                                  unique_travellers=accepted[1], trip_participations=accepted[0],
                                  unresolved_historical_records=unresolved,
                                  identity_totals_partial=unresolved > 0 or unprocessed)



@router.get("/{company_id}/groups", response_model=CompanyGroupPageResponse)
async def company_groups(
    company_id: uuid.UUID, search: str = Query(default="", max_length=120),
    status: Literal["active", "closed", "archived", "all"] = "all", import_only: bool | None = None,
    cursor: str | None = Query(default=None, max_length=2048), page_size: int = Query(default=50, ge=1, le=100),
    agency_id: uuid.UUID | None = None, user: User = Depends(require_role(COMPANY_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
) -> CompanyGroupPageResponse:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    codec = MCPReadCursor(settings.app_secret_key, "company-groups-v1")
    try:
        state = codec.read(cursor, {"user": user.id, "agency": company.agency_id, "company": company.id,
                                    "search": search, "status": status, "import_only": import_only})
    except ValueError as exc:
        raise ValidationError(str(exc), field="cursor") from exc
    query = visible_company_groups(user, company.agency_id, company.id)
    if search.strip():
        query = query.where(substring_predicate(search.strip(), fields=group_search_fields()))
    if status != "all":
        query = query.where(ClientGroupModel.status == status)
    if import_only is not None:
        query = query.where(ClientGroupModel.import_only == import_only)
    if after := codec.after(state):
        query = query.where(or_(ClientGroupModel.created_at < after[0], and_(
            ClientGroupModel.created_at == after[0], ClientGroupModel.id < after[1],
        )))
    columns = (ClientGroupModel.id, ClientGroupModel.name, ClientGroupModel.destination,
               ClientGroupModel.travel_date, ClientGroupModel.return_date, ClientGroupModel.status,
               ClientGroupModel.import_only, ClientGroupModel.company_id, ClientGroupModel.company_revision,
               ClientGroupModel.created_at)
    rows = list((await session.execute(query.with_only_columns(*columns).where(
        ClientGroupModel.created_at <= datetime.fromisoformat(state["cutoff"]),
    ).order_by(ClientGroupModel.created_at.desc(), ClientGroupModel.id.desc()).limit(page_size + 1))).mappings())
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    group_ids = [row["id"] for row in rows]
    traveller_counts = await group_traveller_counts(session, user=user, agency_id=company.agency_id,
        company_id=company.id, group_ids=group_ids)
    counts = dict((await session.execute(select(PassportSubmissionModel.group_id, func.count()).where(
        PassportSubmissionModel.agency_id == company.agency_id, PassportSubmissionModel.group_id.in_(group_ids),
        PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
    ).group_by(PassportSubmissionModel.group_id))).all()) if group_ids else {}
    return CompanyGroupPageResponse(
        items=[CompanyGroupResponse(**{key: value for key, value in row.items() if key != "created_at"},
                                    returning_travellers=traveller_counts.get(row["id"], GroupTravellerCounts()).returning_travellers,
                                    trip_participations=traveller_counts.get(row["id"], GroupTravellerCounts()).trip_participations,
                                    reuse_completed=traveller_counts.get(row["id"], GroupTravellerCounts()).reuse_completed,
                                    submission_count=counts.get(row["id"], 0)) for row in rows],
        next_cursor=codec.next(state, dict(rows[-1])) if has_more else None, has_more=has_more,
    )
