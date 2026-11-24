"""Manager invitations and paginated manager account listing."""

from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.password import hash_password, run_password_work
from app.domain.entities.entities import (
    User,
    UserRole,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    ManagerGroupAccessModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.presentation.api.v1.pagination import PageOffset, PageSize
from app.presentation.api.v1.routes.admin_account_scope import _manager_scope
from app.presentation.api.v1.routes.admin_account_views import (
    _group_response,
    _validated_credential_state,
)
from app.presentation.api.v1.routes.admin_group_projection import index_account_groups
from app.presentation.api.v1.schemas.operations_schemas import (
    CreateManagerRequest,
    ManagerResponse,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()


@router.get(
    "/managers",
    response_model=list[ManagerResponse],
    status_code=status.HTTP_200_OK,
    summary="List manager accounts",
)
async def list_managers(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
    skip: PageOffset = 0,
    limit: PageSize = 100,
) -> list[ManagerResponse]:
    stmt = (
        select(UserModel)
        .where(*_manager_scope(current_user))
        .order_by(UserModel.created_at.desc(), UserModel.id.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    managers = list(result.scalars().all())
    if not managers:
        return []

    manager_ids = [user.id for user in managers]
    groups_result = await session.execute(
        select(ClientGroupModel).where(
            ClientGroupModel.agency_id.in_([user.agency_id for user in managers if user.agency_id]),
            or_(
                ClientGroupModel.created_by_user_id.in_(manager_ids),
                ClientGroupModel.id.in_(
                    select(ManagerGroupAccessModel.group_id).where(
                        ManagerGroupAccessModel.manager_id.in_(manager_ids)
                    )
                ),
            ),
        )
    )
    groups = list(groups_result.scalars().all())
    access_result = await session.execute(
        select(ManagerGroupAccessModel).where(ManagerGroupAccessModel.manager_id.in_(manager_ids))
    )
    access_rows = list(access_result.scalars().all())
    security_result = await session.execute(
        select(UserSecurityStateModel).where(UserSecurityStateModel.user_id.in_(manager_ids))
    )
    security_by_user_id = {state.user_id: state for state in security_result.scalars().all()}
    account_groups = index_account_groups(groups, access_rows)

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
            created_groups=[
                _group_response(group) for group in account_groups.created.get(user.id, [])
            ],
            assigned_groups=[
                _group_response(group) for group in account_groups.assigned.get(user.id, [])
            ],
            credential_state=(
                _validated_credential_state(security_by_user_id[user.id].credential_state)
                if user.id in security_by_user_id
                else "active"
            ),
        )
        for user in managers
    ]


@router.post(
    "/managers",
    response_model=ManagerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a limited manager account",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def create_manager(
    body: CreateManagerRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> ManagerResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assign the admin to an agency before creating managers",
        )

    existing = await session.execute(
        select(UserModel).where(UserModel.email == str(body.email).lower().strip())
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists"
        )

    manager = UserModel(
        email=str(body.email).lower().strip(),
        hashed_password=await run_password_work(hash_password, f"Inv1{secrets.token_urlsafe(32)}"),
        full_name=body.full_name.strip(),
        role=UserRole.AGENCY_MANAGER.value,
        agency_id=current_user.agency_id,
        is_active=True,
    )
    session.add(manager)
    await session.flush()
    identity_repository = IdentitySecurityRepository(session)
    security_state = UserSecurityStateModel(
        user_id=manager.id,
        credential_state="invited",
        session_version=1,
        mfa_required=True,
    )
    session.add(security_state)
    _, activation_token = await identity_repository.issue_action_token(
        user_id=manager.id,
        purpose="activation",
        expires_in=timedelta(days=7),
        created_by_user_id=current_user.id,
    )
    await AuditLogRepository(session).record(
        action="manager.invited",
        entity_type="user_account",
        entity_id=str(manager.id),
        agency_id=manager.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=trusted_client_ip(request),
        metadata={"target_role": manager.role, "target_email": manager.email},
    )
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"

    return ManagerResponse(
        id=manager.id,
        full_name=manager.full_name,
        email=manager.email,
        role=manager.role,
        agency_id=manager.agency_id,
        is_active=manager.is_active,
        created_at=manager.created_at,
        last_login_at=manager.last_login_at,
        credential_state=_validated_credential_state(security_state.credential_state),
        activation_token=activation_token,
    )
