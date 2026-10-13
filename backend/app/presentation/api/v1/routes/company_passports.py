"""Masked document inventory and explicit administrative unusable declarations."""

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import (
    COMPANY_ADMIN_ROLES,
    require_company,
    visible_company_groups,
)
from app.application.travellers.document_lifecycle import block_passport
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.domain.entities.entities import User
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel,
    TravellerParticipationModel,
    TravellerPassportModel,
    TravellerProfileModel,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf


def private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(dependencies=[Depends(private_response), Depends(require_cookie_csrf)])


class PassportInventoryItem(BaseModel):
    id: uuid.UUID
    passport_hint: str
    issuing_country: str
    document_type: str
    status: str
    is_default: bool
    revision: int
    issue_date: date | None
    expiry_date: date | None


class PassportInventoryResponse(BaseModel):
    items: list[PassportInventoryItem]
    profile_revision: int
    limit_reached: bool


class BlockPassportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["lost", "cancelled", "compromised"]
    expected_profile_revision: int = Field(ge=1)
    expected_passport_revision: int = Field(ge=1)


async def visible_profile(session: AsyncSession, *, user: User, company_id: uuid.UUID,
                          agency_id: uuid.UUID | None, traveller_id: uuid.UUID, lock: bool = False) -> TravellerProfileModel:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    visible = visible_company_groups(user, company.agency_id, company_id).with_only_columns(ClientGroupModel.id)
    membership = exists(select(TravellerParticipationModel.id).where(
        TravellerParticipationModel.agency_id == company.agency_id,
        TravellerParticipationModel.company_id == company_id,
        TravellerParticipationModel.traveller_id == traveller_id,
        TravellerParticipationModel.group_id.in_(visible), TravellerParticipationModel.status != "withdrawn"))
    query = select(TravellerProfileModel).where(TravellerProfileModel.id == traveller_id,
        TravellerProfileModel.agency_id == company.agency_id, TravellerProfileModel.company_id == company_id,
        TravellerProfileModel.deleted_at.is_(None), membership)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    profile = await session.scalar(query)
    if profile is None:
        raise HTTPException(404, "Traveller unavailable")
    return profile


@router.get("/{company_id}/travellers/{traveller_id}/passports", response_model=PassportInventoryResponse)
async def passport_inventory(company_id: uuid.UUID, traveller_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
) -> PassportInventoryResponse:
    profile = await visible_profile(session, user=user, company_id=company_id, agency_id=agency_id, traveller_id=traveller_id)
    passport, revision = TravellerPassportModel, TravellerDocumentRevisionModel
    latest = select(revision.id).where(revision.passport_id == passport.id,
        revision.agency_id == profile.agency_id, revision.company_id == company_id,
        revision.traveller_id == profile.id, revision.status == "accepted").order_by(
            revision.revision_number.desc()).limit(1).correlate(passport).scalar_subquery()
    rows = (await session.execute(select(passport, revision.issue_date, revision.expiry_date)
        .outerjoin(revision, revision.id == latest).where(passport.agency_id == profile.agency_id,
            passport.company_id == company_id, passport.traveller_id == profile.id)
        .order_by(passport.is_default.desc(), passport.id).limit(51))).all()
    crypto = TravellerReuseCrypto(get_traveller_reuse_settings())
    return PassportInventoryResponse(items=[PassportInventoryItem(id=item.id,
        passport_hint="********" + crypto.decrypt(item.number_ciphertext)[-2:],
        issuing_country=item.issuing_country, document_type=item.document_type, status=item.status,
        is_default=item.is_default, revision=item.revision, issue_date=issue, expiry_date=expiry,
    ) for item, issue, expiry in rows[:50]], profile_revision=profile.revision, limit_reached=len(rows) > 50)


@router.patch("/{company_id}/travellers/{traveller_id}/passports/{passport_id}", status_code=204)
async def declare_passport_unusable(company_id: uuid.UUID, traveller_id: uuid.UUID, passport_id: uuid.UUID,
    body: BlockPassportBody, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
) -> Response:
    profile = await visible_profile(session, user=user, company_id=company_id, agency_id=agency_id,
        traveller_id=traveller_id, lock=True)
    await block_passport(session, profile=profile, passport_id=passport_id,
        expected_profile_revision=body.expected_profile_revision, expected_passport_revision=body.expected_passport_revision,
        status=body.status, actor_id=user.id)
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})
