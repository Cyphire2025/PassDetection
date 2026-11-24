"""Bounded client-manager directory, session and audit routes."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerProfileModel,
    ClientOrganizationModel,
    MobileDeviceSessionModel,
)
from app.infrastructure.database.models import (
    AuditLogModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.gc_app_history_support import (
    client_manager_session_responses,
    gc_app_audit_responses,
)
from app.presentation.api.v1.routes.gc_app_manager_support import (
    _manager_group_map,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    GC_ADMIN_ROLES,
    _client_manager_response,
    _get_client_manager,
    _tenant_id,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerPageResponse,
    ClientManagerSessionPageResponse,
    GCAppAuditPageResponse,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()


@router.get("/client-managers", response_model=ClientManagerPageResponse)
async def list_client_managers(
    q: str | None = Query(default=None, max_length=120),
    account_status: Literal["invited", "active", "suspended", "deleted"] | None = Query(
        default=None,
        alias="status",
    ),
    company_id: uuid.UUID | None = None,
    agency_id: uuid.UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ClientManagerPageResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    filters = [
        ClientManagerProfileModel.agency_id == tenant_id,
        UserModel.role == UserRole.CLIENT_MANAGER.value,
        UserModel.agency_id == tenant_id,
    ]
    if account_status == "deleted":
        filters.append(ClientManagerProfileModel.deleted_at.is_not(None))
    else:
        filters.append(ClientManagerProfileModel.deleted_at.is_(None))
    if q and (normalized := " ".join(q.split())):
        phone_search = "".join(character for character in normalized if character.isdigit())
        filters.append(
            UserModel.full_name.icontains(normalized, autoescape=True)
            | UserModel.email.icontains(normalized, autoescape=True)
            | ClientManagerProfileModel.normalized_phone_number.icontains(
                phone_search if len(phone_search) >= 3 else normalized,
                autoescape=True,
            )
        )
    if account_status is not None:
        filters.append(ClientManagerProfileModel.status == account_status)
    if company_id is not None:
        filters.append(ClientManagerProfileModel.organization_id == company_id)
    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ClientManagerProfileModel)
                .join(UserModel, UserModel.id == ClientManagerProfileModel.user_id)
                .where(*filters)
            )
        ).scalar_one()
    )
    rows = (
        await session.execute(
            select(ClientManagerProfileModel, UserModel, ClientOrganizationModel)
            .join(UserModel, UserModel.id == ClientManagerProfileModel.user_id)
            .join(
                ClientOrganizationModel,
                ClientOrganizationModel.id == ClientManagerProfileModel.organization_id,
            )
            .where(*filters)
            .order_by(
                ClientManagerProfileModel.created_at.desc(),
                ClientManagerProfileModel.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()
    group_map = await _manager_group_map(
        session, [profile.id for profile, _user, _organization in rows]
    )
    return ClientManagerPageResponse(
        items=[
            _client_manager_response(profile, user, organization, group_map.get(profile.id, []))
            for profile, user, organization in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/client-managers/{profile_id}/sessions",
    response_model=ClientManagerSessionPageResponse,
)
async def list_client_manager_sessions(
    profile_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ClientManagerSessionPageResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    _profile, user, _organization = await _get_client_manager(
        session, tenant_id, profile_id, lock=False
    )
    filters = (
        MobileDeviceSessionModel.agency_id == tenant_id,
        MobileDeviceSessionModel.user_id == user.id,
    )
    total = int(
        await session.scalar(select(func.count(MobileDeviceSessionModel.id)).where(*filters)) or 0
    )
    items = list(
        (
            await session.execute(
                select(MobileDeviceSessionModel)
                .where(
                    *filters,
                )
                .order_by(
                    MobileDeviceSessionModel.created_at.desc(),
                    MobileDeviceSessionModel.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return ClientManagerSessionPageResponse(
        items=client_manager_session_responses(items),
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/client-managers/{profile_id}/audit",
    response_model=GCAppAuditPageResponse,
)
async def list_client_manager_audit(
    profile_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GCAppAuditPageResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    await _get_client_manager(session, tenant_id, profile_id, lock=False)
    filters = (
        AuditLogModel.agency_id == tenant_id,
        AuditLogModel.entity_type == "client_manager_profile",
        AuditLogModel.entity_id == str(profile_id),
    )
    total = int(await session.scalar(select(func.count(AuditLogModel.id)).where(*filters)) or 0)
    logs = list(
        (
            await session.execute(
                select(AuditLogModel)
                .where(
                    *filters,
                )
                .order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return GCAppAuditPageResponse(
        items=gc_app_audit_responses(logs),
        total=total,
        offset=offset,
        limit=limit,
    )
