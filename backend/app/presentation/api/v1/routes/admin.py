"""
Admin Routes
============
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.password import hash_password
from app.domain.entities.entities import PassportProcessingStatus, User, UserRole
from app.infrastructure.database.models import AgencyModel, ClientGroupModel, PassportSubmissionModel, UserModel
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.schemas.operations_schemas import (
    AdminOverviewResponse,
    CreateManagerRequest,
    ManagerResponse,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()


def _manager_scope(current_user: User) -> list:
    if current_user.role == UserRole.SUPER_ADMIN:
        return [UserModel.role == UserRole.AGENCY_STAFF.value]
    return [
        UserModel.role == UserRole.AGENCY_STAFF.value,
        UserModel.agency_id == current_user.agency_id,
    ]


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
    agency_filter = [] if current_user.role == UserRole.SUPER_ADMIN else [AgencyModel.id == current_user.agency_id]
    user_filter = [] if current_user.role == UserRole.SUPER_ADMIN else [UserModel.agency_id == current_user.agency_id]
    group_filter = [] if current_user.role == UserRole.SUPER_ADMIN else [ClientGroupModel.agency_id == current_user.agency_id]
    passport_filter = [] if current_user.role == UserRole.SUPER_ADMIN else [PassportSubmissionModel.agency_id == current_user.agency_id]

    agencies = await _count(session, select(func.count()).select_from(AgencyModel).where(*agency_filter))
    users = await _count(session, select(func.count()).select_from(UserModel).where(*user_filter))
    groups = await _count(session, select(func.count()).select_from(ClientGroupModel).where(*group_filter))
    passports = await _count(session, select(func.count()).select_from(PassportSubmissionModel).where(*passport_filter))
    pending = await _count(
        session,
        select(func.count()).select_from(PassportSubmissionModel).join(
            ClientGroupModel,
            PassportSubmissionModel.group_id == ClientGroupModel.id,
        ).where(
            *passport_filter,
            PassportSubmissionModel.status == PassportProcessingStatus.REVIEW_REQUIRED.value,
            ClientGroupModel.status != "archived",
        ),
    )
    submitted = await _count(
        session,
        select(func.count()).select_from(PassportSubmissionModel).join(
            ClientGroupModel,
            PassportSubmissionModel.group_id == ClientGroupModel.id,
        ).where(
            *passport_filter,
            PassportSubmissionModel.status == PassportProcessingStatus.CLIENT_SUBMITTED.value,
            ClientGroupModel.status != "archived",
        ),
    )
    failed = await _count(
        session,
        select(func.count()).select_from(PassportSubmissionModel).join(
            ClientGroupModel,
            PassportSubmissionModel.group_id == ClientGroupModel.id,
        ).where(
            *passport_filter,
            PassportSubmissionModel.status == PassportProcessingStatus.FAILED.value,
            ClientGroupModel.status != "archived",
        ),
    )
    return AdminOverviewResponse(
        agencies=agencies,
        users=users,
        client_groups=groups,
        passport_submissions=passports,
        pending_review=pending,
        client_submitted=submitted,
        failed=failed,
    )


@router.get(
    "/managers",
    response_model=list[ManagerResponse],
    status_code=status.HTTP_200_OK,
    summary="List manager accounts",
)
async def list_managers(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
    skip: int = 0,
    limit: int = 100,
) -> list[ManagerResponse]:
    stmt = (
        select(UserModel)
        .where(*_manager_scope(current_user))
        .order_by(UserModel.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [
        ManagerResponse(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            role=user.role,
            agency_id=user.agency_id,
            is_active=user.is_active,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )
        for user in result.scalars().all()
    ]


@router.post(
    "/managers",
    response_model=ManagerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a limited manager account",
)
async def create_manager(
    body: CreateManagerRequest,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> ManagerResponse:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assign the admin to an agency before creating managers")

    existing = await session.execute(select(UserModel).where(UserModel.email == str(body.email).lower().strip()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")

    manager = UserModel(
        email=str(body.email).lower().strip(),
        hashed_password=hash_password(body.password),
        full_name=body.full_name.strip(),
        role=UserRole.AGENCY_STAFF.value,
        agency_id=current_user.agency_id,
        is_active=True,
    )
    session.add(manager)
    await session.flush()

    return ManagerResponse(
        id=manager.id,
        full_name=manager.full_name,
        email=manager.email,
        role=manager.role,
        agency_id=manager.agency_id,
        is_active=manager.is_active,
        created_at=manager.created_at,
        last_login_at=manager.last_login_at,
    )


async def _count(session: AsyncSession, stmt) -> int:  # type: ignore[no-untyped-def]
    result = await session.execute(stmt)
    return int(result.scalar_one())
