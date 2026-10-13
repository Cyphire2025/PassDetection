"""Bounded company history under the identical visible-group population.

One page query plus one aggregate for at most 100 selected people. Names are
encrypted; exact full-name search uses a tenant-scoped HMAC index. Opening this
projection never fetches a passport image or returns storage locators.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import (
    COMPANY_ADMIN_ROLES,
    require_company,
    visible_company_groups,
)
from app.application.mcp.read_cursor import MCPReadCursor
from app.core.config.settings import Settings, get_settings
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel,
    TravellerParticipationModel,
    TravellerProfileModel,
)
from app.infrastructure.security.traveller_reuse_crypto import (
    ReuseCryptoUnavailable,
    TravellerReuseCrypto,
)
from app.presentation.api.v1.schemas.company_traveller_schemas import (
    CompanyTravellerPage,
    CompanyTravellerResponse,
    TravellerHistoryPage,
    TravellerHistoryResponse,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()


def _crypto() -> TravellerReuseCrypto:
    try:
        return TravellerReuseCrypto(get_traveller_reuse_settings())
    except ReuseCryptoUnavailable as exc:
        raise HTTPException(503, "Traveller history is temporarily unavailable.") from exc


@router.get("/{company_id}/travellers", response_model=CompanyTravellerPage)
async def company_travellers(
    company_id: uuid.UUID, response: Response, agency_id: uuid.UUID | None = None,
    search: str = Query(default="", max_length=120), cursor: str | None = Query(default=None, max_length=2048),
    page_size: int = Query(default=30, ge=1, le=100),
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))),
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
) -> CompanyTravellerPage:
    response.headers["Cache-Control"] = "private, no-store"
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    groups = visible_company_groups(user, company.agency_id, company.id).subquery()
    normalized = " ".join(search.split()).casefold()
    codec = MCPReadCursor(settings.app_secret_key, "company-travellers-v1")
    try:
        state = codec.read(cursor, {"actor": str(user.id), "agency": str(company.agency_id), "company": str(company.id), "search": normalized})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    membership = exists(select(TravellerParticipationModel.id).join(groups, groups.c.id == TravellerParticipationModel.group_id).where(
        TravellerParticipationModel.traveller_id == TravellerProfileModel.id,
        TravellerParticipationModel.agency_id == company.agency_id,
        TravellerParticipationModel.company_id == company.id,
        TravellerParticipationModel.status == "accepted",
    ))
    query = select(TravellerProfileModel).where(
        TravellerProfileModel.agency_id == company.agency_id,
        TravellerProfileModel.company_id == company.id,
        TravellerProfileModel.deleted_at.is_(None), membership,
        TravellerProfileModel.created_at <= datetime.fromisoformat(state["cutoff"]),
    )
    if normalized:
        try:
            query = query.where(TravellerProfileModel.id == uuid.UUID(normalized))
        except ValueError:
            crypto = _crypto()
            query = query.where(
                TravellerProfileModel.name_fingerprint == crypto.scoped_digest("name", company.agency_id, company.id, normalized),
                TravellerProfileModel.fingerprint_key_version == crypto.key_version,
            )
    after = codec.after(state)
    if after:
        query = query.where(or_(TravellerProfileModel.created_at < after[0], and_(TravellerProfileModel.created_at == after[0], TravellerProfileModel.id < after[1])))
    rows = list((await session.scalars(query.order_by(TravellerProfileModel.created_at.desc(), TravellerProfileModel.id.desc()).limit(page_size + 1))).all())
    has_more, rows = len(rows) > page_size, rows[:page_size]
    if not rows:
        return CompanyTravellerPage(items=[], next_cursor=None)
    ids = [row.id for row in rows]
    aggregate = (await session.execute(select(
        TravellerParticipationModel.traveller_id, func.count(TravellerParticipationModel.id), func.max(groups.c.travel_date),
    ).join(groups, groups.c.id == TravellerParticipationModel.group_id).where(
        TravellerParticipationModel.agency_id == company.agency_id,
        TravellerParticipationModel.company_id == company.id,
        TravellerParticipationModel.traveller_id.in_(ids), TravellerParticipationModel.status == "accepted",
    ).group_by(TravellerParticipationModel.traveller_id))).all()
    counts = {row[0]: (row[1], row[2]) for row in aggregate}
    crypto = _crypto()
    items = [CompanyTravellerResponse(
        id=row.id, display_name=crypto.decrypt(row.display_name_ciphertext) if row.display_name_ciphertext else "Traveller",
        status=row.status, participation_count=counts[row.id][0], last_trip_date=counts[row.id][1],
    ) for row in rows]
    next_cursor = codec.next(state, {"id": rows[-1].id, "created_at": rows[-1].created_at}) if has_more else None
    return CompanyTravellerPage(items=items, next_cursor=next_cursor)


@router.get("/{company_id}/travellers/{traveller_id}/history", response_model=TravellerHistoryPage)
async def company_traveller_history(
    company_id: uuid.UUID, traveller_id: uuid.UUID, response: Response,
    agency_id: uuid.UUID | None = None, cursor: str | None = Query(default=None, max_length=2048),
    page_size: int = Query(default=30, ge=1, le=100),
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))),
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
) -> TravellerHistoryPage:
    response.headers["Cache-Control"] = "private, no-store"
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    groups = visible_company_groups(user, company.agency_id, company.id).subquery()
    codec = MCPReadCursor(settings.app_secret_key, "company-traveller-history-v1")
    try:
        state = codec.read(cursor, {"actor": str(user.id), "agency": str(company.agency_id), "company": str(company.id), "traveller": str(traveller_id)})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    query = select(
        TravellerParticipationModel.id, TravellerParticipationModel.created_at,
        TravellerParticipationModel.group_id, groups.c.name, groups.c.travel_date,
        groups.c.status, TravellerParticipationModel.status,
        TravellerDocumentRevisionModel.revision_number,
    ).join(groups, groups.c.id == TravellerParticipationModel.group_id).join(
        TravellerProfileModel, TravellerProfileModel.id == TravellerParticipationModel.traveller_id,
    ).outerjoin(TravellerDocumentRevisionModel, (TravellerDocumentRevisionModel.id == TravellerParticipationModel.document_revision_id)
                & (TravellerDocumentRevisionModel.agency_id == company.agency_id)
                & (TravellerDocumentRevisionModel.company_id == company.id)).where(
        TravellerParticipationModel.agency_id == company.agency_id,
        TravellerParticipationModel.company_id == company.id,
        TravellerParticipationModel.traveller_id == traveller_id,
        TravellerProfileModel.deleted_at.is_(None), TravellerParticipationModel.status != "withdrawn",
        TravellerParticipationModel.created_at <= datetime.fromisoformat(state["cutoff"]),
    )
    after = codec.after(state)
    if after:
        query = query.where(or_(TravellerParticipationModel.created_at < after[0], and_(TravellerParticipationModel.created_at == after[0], TravellerParticipationModel.id < after[1])))
    rows = (await session.execute(query.order_by(TravellerParticipationModel.created_at.desc(), TravellerParticipationModel.id.desc()).limit(page_size + 1))).all()
    has_more, rows = len(rows) > page_size, rows[:page_size]
    items = [TravellerHistoryResponse(id=row[0], group_id=row[2], group_name=row[3], travel_date=row[4], lifecycle=row[5], participation_status=row[6], document_revision=row[7]) for row in rows]
    next_cursor = codec.next(state, {"id": rows[-1][0], "created_at": rows[-1][1]}) if has_more else None
    return TravellerHistoryPage(items=items, next_cursor=next_cursor)
