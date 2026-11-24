"""Private, single-use staff invitation endpoint."""

from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.password import hash_password, run_password_work
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.presentation.api.v1.routes.managed_account_scope import STAFF_ADMIN_ROLES
from app.presentation.api.v1.routes.managed_account_values import (
    _account_response,
    _audit_account_action,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    CreateStaffRequest,
    ManagedAccountResponse,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/staff",
    response_model=ManagedAccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a staff account",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def create_staff_account(
    body: CreateStaffRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(require_role(STAFF_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ManagedAccountResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assign the admin to an agency before creating staff",
        )

    email = str(body.email).lower().strip()
    existing = await session.execute(select(UserModel).where(UserModel.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists"
        )

    staff = UserModel(
        email=email,
        hashed_password=await run_password_work(hash_password, f"Inv1{secrets.token_urlsafe(32)}"),
        full_name=body.full_name.strip(),
        role=UserRole.AGENCY_STAFF.value,
        agency_id=current_user.agency_id,
        is_active=True,
    )
    session.add(staff)
    await session.flush()
    identity_repository = IdentitySecurityRepository(session)
    security_state = UserSecurityStateModel(
        user_id=staff.id,
        credential_state="invited",
        session_version=1,
        mfa_required=True,
    )
    session.add(security_state)
    _, activation_token = await identity_repository.issue_action_token(
        user_id=staff.id,
        purpose="activation",
        expires_in=timedelta(days=7),
        created_by_user_id=current_user.id,
    )
    await _audit_account_action(session, current_user, request, staff, "staff.invited")

    agency_name = None
    if staff.agency_id:
        agency_name = (
            await session.execute(select(AgencyModel.name).where(AgencyModel.id == staff.agency_id))
        ).scalar_one_or_none()
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return _account_response(
        staff,
        agency_name,
        security_state,
        activation_token=activation_token,
    )
