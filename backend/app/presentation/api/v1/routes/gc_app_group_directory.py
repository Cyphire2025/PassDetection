"""Bounded GC agency and group directory routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy import or_ as or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.mobile.group_app_availability import (
    GCAppAvailability,
)
from app.application.mobile.group_app_availability import (
    availability_fields as availability_fields,
)
from app.application.mobile.group_app_availability import (
    availability_filter as availability_filter,
)
from app.domain.entities.entities import GroupStatus as GroupStatus
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.gc_mobile_models import (
    ClientOrganizationModel as ClientOrganizationModel,
)
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel as GCGroupAccessModel,
)
from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel as MobileDeviceSessionModel,
)
from app.infrastructure.database.models import AgencyModel
from app.infrastructure.database.models import ClientGroupModel as ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.gc_app_scope import (
    GC_ADMIN_ROLES,
    _tenant_id,
)
from app.presentation.api.v1.routes.gc_group_directory_filters import (
    build_gc_group_directory_filters,
)
from app.presentation.api.v1.routes.gc_group_directory_projection import project_gc_group_directory
from app.presentation.api.v1.routes.gc_group_directory_query import query_gc_group_directory
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCAgencyPageResponse,
    GCAgencyResponse,
    GCGroupSearchPageResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCGroupSearchAccess as GCGroupSearchAccess,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCGroupSearchItem as GCGroupSearchItem,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()


@router.get("/agencies", response_model=GCAgencyPageResponse)
async def list_gc_agencies(
    q: str | None = Query(default=None, max_length=120),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GCAgencyPageResponse:
    """Return a bounded tenant selector without granting cross-tenant access."""

    filters: list[ColumnElement[bool]] = [AgencyModel.is_active.is_(True)]
    if current_user.role != UserRole.SUPER_ADMIN:
        if current_user.agency_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The account is not assigned to an agency",
            )
        filters.append(AgencyModel.id == current_user.agency_id)
    if q and (normalized := " ".join(q.split())):
        filters.append(
            AgencyModel.name.contains(normalized, autoescape=True)
            | AgencyModel.email.contains(normalized, autoescape=True)
        )
    total = int(
        (
            await session.execute(select(func.count()).select_from(AgencyModel).where(*filters))
        ).scalar_one()
    )
    agencies = list(
        (
            await session.execute(
                select(AgencyModel)
                .where(*filters)
                .order_by(AgencyModel.name.asc(), AgencyModel.id.asc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return GCAgencyPageResponse(
        items=[
            GCAgencyResponse(
                id=agency.id,
                name=agency.name,
                email=agency.email,
                is_active=agency.is_active,
            )
            for agency in agencies
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/groups", response_model=GCGroupSearchPageResponse)
async def search_gc_groups(
    q: str | None = Query(default=None, max_length=120),
    agency_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    gc_enabled: bool | None = None,
    eligible_only: bool = False,
    configured_only: bool = False,
    unconfigured_only: bool = False,
    availability: GCAppAvailability | None = None,
    lifecycle_status: str | None = Query(default=None, max_length=16),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GCGroupSearchPageResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    now = datetime.now(UTC)
    filters, access_join = build_gc_group_directory_filters(
        tenant_id=tenant_id,
        group_id=group_id,
        lifecycle_status=lifecycle_status,
        q=q,
        eligible_only=eligible_only,
        gc_enabled=gc_enabled,
        configured_only=configured_only,
        unconfigured_only=unconfigured_only,
        availability=availability,
        now=now,
    )
    total, rows = await query_gc_group_directory(
        session,
        tenant_id=tenant_id,
        now=now,
        filters=filters,
        access_join=access_join,
        gc_enabled=gc_enabled,
        group_id=group_id,
        configured_only=configured_only,
        offset=offset,
        limit=limit,
    )
    items = project_gc_group_directory(rows, now=now)

    return GCGroupSearchPageResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )
