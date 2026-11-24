"""Administrative overview and explicit retention inspection endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import (
    User,
    UserRole,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.admin_overview_repository import AdminOverviewRepository
from app.infrastructure.repositories.passport_retention_repository import (
    PassportRetentionRepository,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    AdminOverviewResponse,
    PassportRetentionControlResponse,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()


@router.get(
    "/overview",
    response_model=AdminOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Get administrative platform overview",
)
async def get_admin_overview(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> AdminOverviewResponse:
    counts = await AdminOverviewRepository(session).overview(
        role=current_user.role, agency_id=current_user.agency_id
    )
    return AdminOverviewResponse(**counts)


@router.get(
    "/groups/{group_id}/passport-retention",
    response_model=PassportRetentionControlResponse,
    status_code=status.HTTP_200_OK,
    summary="Inspect an explicit group passport-retention schedule",
)
async def get_group_passport_retention(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> PassportRetentionControlResponse:
    schedule = await PassportRetentionRepository(session).get_schedule(
        group_id=group_id,
        role=current_user.role,
        agency_id=current_user.agency_id,
    )
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    return PassportRetentionControlResponse(**schedule.project())
