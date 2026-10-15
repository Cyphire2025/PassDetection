"""Administration contracts for explicit reuse purpose and collection scope."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import COMPANY_ADMIN_ROLES, require_company
from app.application.companies.reuse_setup import (
    REUSE_NOTICE_TEXT,
    require_company_group,
    save_group_reuse_config,
    save_reuse_policy,
)
from app.domain.entities.entities import User
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.traveller_reuse_models import (
    TravellerGroupReuseConfigModel,
    TravellerReusePolicyModel,
)
from app.presentation.api.v1.routes.companies import _private_response
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter(dependencies=[Depends(_private_response)])


class ReusePolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=0)
    enabled: bool
    retention_mode: Literal["until_withdrawn"] = "until_withdrawn"
    purpose_version: str | None = Field(default=None, min_length=1, max_length=128)
    notice_version: str | None = Field(default=None, min_length=1, max_length=128)
    processing_basis: str | None = Field(default=None, min_length=1, max_length=128)


class ReusePolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    company_id: uuid.UUID
    enabled: bool = False
    notice_text: str = REUSE_NOTICE_TEXT
    revision: int = 0
    retention_mode: Literal["until_withdrawn", "limited"] = "until_withdrawn"
    retention_days: int | None = None
    purpose_version: str | None = None
    notice_version: str | None = None
    processing_basis: str | None = None
    configured_at: datetime | None = None


class GroupReuseConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=0)
    expected_group_revision: int = Field(ge=0)
    enabled: bool
    roster_mode: Literal["closed", "open"]
    individual_identifier_type: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    identifier_required: bool = False


class GroupReuseConfigResponse(BaseModel):
    group_id: uuid.UUID
    company_id: uuid.UUID
    group_revision: int
    enabled: bool
    revision: int
    roster_mode: Literal["closed", "open"] = "closed"
    individual_identifier_type: str | None = None
    identifier_required: bool = False


def _config_response(group: ClientGroupModel, config: TravellerGroupReuseConfigModel | None) -> GroupReuseConfigResponse:
    scoped = config if config is not None and config.company_id == group.company_id else None
    # require_company_group has already established a non-null company assignment.
    if group.company_id is None:
        raise ValueError("A company-scoped group is required")
    roster_mode: Literal["closed", "open"] = "open" if scoped and scoped.roster_mode == "open" else "closed"
    return GroupReuseConfigResponse(
        group_id=group.id, company_id=group.company_id, group_revision=group.company_revision,
        enabled=scoped is not None, revision=config.revision if config is not None else 0,
        roster_mode=roster_mode,
        individual_identifier_type=scoped.individual_identifier_type if scoped else None,
        identifier_required=scoped.identifier_required if scoped else False,
    )


@router.get("/{company_id}/reuse-policy", response_model=ReusePolicyResponse)
async def get_company_reuse_policy(
    company_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
) -> ReusePolicyResponse:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    policy = await session.get(TravellerReusePolicyModel, company.id)
    return ReusePolicyResponse.model_validate(policy) if policy else ReusePolicyResponse(company_id=company.id)


@router.put("/{company_id}/reuse-policy", response_model=ReusePolicyResponse, dependencies=[Depends(require_cookie_csrf)])
async def set_company_reuse_policy(
    company_id: uuid.UUID, body: ReusePolicyRequest, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
) -> ReusePolicyResponse:
    policy = await save_reuse_policy(session, user=user, company_id=company_id, agency_id=agency_id,
                                     **body.model_dump(exclude={"retention_mode"}))
    return ReusePolicyResponse.model_validate(policy)


@router.get("/{company_id}/groups/{group_id}/reuse-config", response_model=GroupReuseConfigResponse)
async def get_group_reuse_config(
    company_id: uuid.UUID, group_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
) -> GroupReuseConfigResponse:
    group = await require_company_group(session, user=user, company_id=company_id, agency_id=agency_id, group_id=group_id)
    return _config_response(group, await session.get(TravellerGroupReuseConfigModel, group.id))


@router.put("/{company_id}/groups/{group_id}/reuse-config", response_model=GroupReuseConfigResponse,
             dependencies=[Depends(require_cookie_csrf)])
async def set_group_reuse_config(
    company_id: uuid.UUID, group_id: uuid.UUID, body: GroupReuseConfigRequest, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
) -> GroupReuseConfigResponse:
    group, config = await save_group_reuse_config(session, user=user, company_id=company_id, agency_id=agency_id,
                                                  group_id=group_id, **body.model_dump())
    return _config_response(group, config)
