"""GC client-organization directory and lifecycle routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.directory import create_company, delete_company
from app.domain.entities.entities import User
from app.infrastructure.database.gc_mobile_models import (
    ClientOrganizationModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.gc_app_scope import (
    GC_ADMIN_ROLES,
    _get_organization,
    _organization_response,
    _tenant_id,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientOrganizationCreateRequest,
    ClientOrganizationPageResponse,
    ClientOrganizationResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.get(
    "/client-organizations",
    response_model=list[ClientOrganizationResponse],
)
async def list_client_organizations(
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ClientOrganizationResponse]:
    tenant_id = _tenant_id(current_user, agency_id)
    organizations = list(
        (
            await session.execute(
                select(ClientOrganizationModel)
                .where(
                    ClientOrganizationModel.agency_id == tenant_id,
                    ClientOrganizationModel.status == "active",
                )
                .order_by(ClientOrganizationModel.name.asc())
                .limit(200)
            )
        ).scalars()
    )
    return [_organization_response(item) for item in organizations]


@router.get(
    "/client-organizations/search",
    response_model=ClientOrganizationPageResponse,
)
async def search_client_organizations(
    q: str | None = Query(default=None, max_length=120),
    agency_id: uuid.UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ClientOrganizationPageResponse:
    """Return a bounded, tenant-scoped company/client directory page."""

    tenant_id = _tenant_id(current_user, agency_id)
    filters = [
        ClientOrganizationModel.agency_id == tenant_id,
        ClientOrganizationModel.status == "active",
    ]
    if q and (normalized := " ".join(q.split())):
        filters.append(ClientOrganizationModel.name.icontains(normalized, autoescape=True))
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(ClientOrganizationModel).where(*filters)
            )
        ).scalar_one()
    )
    organizations = list(
        (
            await session.execute(
                select(ClientOrganizationModel)
                .where(*filters)
                .order_by(
                    ClientOrganizationModel.name.asc(),
                    ClientOrganizationModel.id.asc(),
                )
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return ClientOrganizationPageResponse(
        items=[_organization_response(item) for item in organizations],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/client-organizations",
    response_model=ClientOrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def create_client_organization(
    body: ClientOrganizationCreateRequest,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ClientOrganizationResponse:
    organization = await create_company(
        session,
        user=current_user,
        agency_id=agency_id,
        name=body.name,
    )
    return _organization_response(organization)


@router.delete(
    "/client-organizations/{organization_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_cookie_csrf)],
)
async def delete_client_organization(
    organization_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Soft-delete an unused client organization without touching travel data."""

    tenant_id = _tenant_id(current_user, agency_id)
    organization = await _get_organization(session, tenant_id, organization_id, lock=True)
    await delete_company(
        session,
        user=current_user,
        company_id=organization_id,
        agency_id=tenant_id,
        expected_revision=organization.revision,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
