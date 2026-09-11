"""Superadmin-only, same-account access-level selection."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthenticationError, AuthorizationError
from app.infrastructure.database.models import AgencyModel, ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.auth_schemas import AccessLevelRequest, UserResponse
from app.presentation.dependencies.auth import get_authenticated_user
from app.presentation.security.access_level import (
    apply_access_level,
    apply_access_level_cookie,
    clear_access_level_cookie,
    set_access_level_cookie,
)
from app.presentation.security.auth_user_response import user_response
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()


async def _resolve_agency(
    *, session: AsyncSession, user: User, requested_id: uuid.UUID | None,
    request: Request,
) -> AgencyModel:
    agency_id = requested_id
    if agency_id is None:
        try:
            effective = apply_access_level_cookie(user, request.cookies, request.state.auth_claims)
            agency_id = effective.agency_id
        except AuthenticationError:
            pass
        agency_id = agency_id or user.agency_id
    if agency_id is None:
        agency_id = await session.scalar(
            select(ClientGroupModel.agency_id)
            .join(AgencyModel, AgencyModel.id == ClientGroupModel.agency_id)
            .where(ClientGroupModel.created_by_user_id == user.id,
                   ClientGroupModel.status == "active", ClientGroupModel.deleted_at.is_(None),
                   AgencyModel.is_active.is_(True))
            .order_by(ClientGroupModel.created_at.desc(), ClientGroupModel.id.desc()).limit(1)
        )
    if agency_id is not None:
        agency = await session.scalar(
            select(AgencyModel).where(AgencyModel.id == agency_id, AgencyModel.is_active.is_(True))
        )
        if agency is None:
            raise HTTPException(409, "The selected agency is not active")
        return agency
    agencies = list((await session.scalars(
        select(AgencyModel).where(AgencyModel.is_active.is_(True)).limit(2)
    )).all())
    if len(agencies) != 1:
        choices = list((await session.scalars(
            select(AgencyModel).where(AgencyModel.is_active.is_(True))
            .order_by(AgencyModel.name, AgencyModel.id)
        )).all())
        raise HTTPException(409, {
            "code": "ACCESS_LEVEL_AGENCY_REQUIRED",
            "message": "Select an agency before changing access level",
            "agencies": [{"id": str(agency.id), "name": agency.name} for agency in choices],
        })
    return agencies[0]


@router.post("/access-level", response_model=UserResponse)
async def switch_access_level(
    body: AccessLevelRequest,
    request: Request,
    response: Response,
    user: User = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    # Authenticate the true identity so any selected mode can always be exited.
    # This deliberate access reduction never challenges or renews MFA/session tokens.
    if user.role != UserRole.SUPER_ADMIN or not user.is_active:
        raise AuthorizationError("Only Super Admin can change their access level")
    role = UserRole(body.role)
    selected = user
    if role == UserRole.SUPER_ADMIN:
        clear_access_level_cookie(response)
    else:
        agency = await _resolve_agency(
            session=session, user=user, requested_id=body.agency_id, request=request,
        )
        selected = apply_access_level(
            user, role=role, agency_id=agency.id, agency_name=agency.name,
        )
        set_access_level_cookie(
            response, user=user, role=role, agency_id=agency.id, agency_name=agency.name,
            claims=request.state.auth_claims,
        )
    await AuditLogRepository(session).record(
        action="auth.access_level_changed", entity_type="user_account",
        agency_id=selected.agency_id, user_id=user.id, actor_email=user.email,
        entity_id=str(user.id), ip_address=trusted_client_ip(request),
        metadata={"actual_role": user.role.value, "access_level": role.value},
    )
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    return user_response(selected)
