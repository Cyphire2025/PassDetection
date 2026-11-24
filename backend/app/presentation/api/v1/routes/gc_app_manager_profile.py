"""Client-manager profile and account lifecycle routes."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.core.security.password import hash_password, run_password_work
from app.domain.entities.entities import User
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
)
from app.infrastructure.database.models import (
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.gc_app_manager_support import (
    _manager_group_map,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    GC_ADMIN_ROLES,
    _audit,
    _client_manager_response,
    _get_client_manager,
    _get_organization,
    _require_revision,
    _tenant_id,
)
from app.presentation.api.v1.routes.gc_app_sessions import (
    _revoke_mobile_sessions,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerForcePasswordChangeRequest,
    ClientManagerResponse,
    ClientManagerStatusRequest,
    ClientManagerUpdateRequest,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.patch(
    "/client-managers/{profile_id}",
    response_model=ClientManagerResponse,
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def update_client_manager(
    profile_id: uuid.UUID,
    body: ClientManagerUpdateRequest,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ClientManagerResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    profile, user, organization = await _get_client_manager(
        session, tenant_id, profile_id, lock=True
    )
    _require_revision(profile.revision, body.expected_revision)
    now = datetime.now(tz=UTC)
    if body.email is not None:
        email = str(body.email).lower().strip()
        duplicate = (
            await session.execute(
                select(UserModel.id).where(UserModel.email == email, UserModel.id != user.id)
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email is already in use"
            )
        user.email = email
    if body.full_name is not None:
        user.full_name = " ".join(body.full_name.split())
    if body.phone_number is not None:
        normalized_phone = normalize_whatsapp_phone(body.phone_number)
        if normalized_phone is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Phone number is not valid for WhatsApp/mobile matching",
            )
        profile.normalized_phone_number = normalized_phone
    if body.organization_id is not None and body.organization_id != profile.organization_id:
        organization = await _get_organization(session, tenant_id, body.organization_id, lock=True)
        await session.execute(
            update(ClientManagerGroupAssignmentModel)
            .where(
                ClientManagerGroupAssignmentModel.profile_id == profile.id,
                ClientManagerGroupAssignmentModel.agency_id == tenant_id,
            )
            .values(
                organization_id=None,
                is_active=False,
                revoked_by_user_id=case(
                    (ClientManagerGroupAssignmentModel.is_active.is_(True), current_user.id),
                    else_=ClientManagerGroupAssignmentModel.revoked_by_user_id,
                ),
                revoked_at=func.coalesce(ClientManagerGroupAssignmentModel.revoked_at, now),
                updated_at=now,
            )
        )
        profile.organization_id = organization.id
        profile.access_generation += 1
        await _revoke_mobile_sessions(session, tenant_id, user.id, "client_organization_changed")
    profile.revision += 1
    profile.updated_by_user_id = current_user.id
    profile.updated_at = now
    user.updated_at = now
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action="gc_app.client_manager_updated",
        entity_type="client_manager_profile",
        entity_id=profile.id,
        metadata=None,
    )
    assigned_groups = (await _manager_group_map(session, [profile.id])).get(profile.id, [])
    return _client_manager_response(profile, user, organization, assigned_groups)


@router.patch(
    "/client-managers/{profile_id}/status",
    response_model=ClientManagerResponse,
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def set_client_manager_status(
    profile_id: uuid.UUID,
    body: ClientManagerStatusRequest,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ClientManagerResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    profile, user, organization = await _get_client_manager(
        session, tenant_id, profile_id, lock=True
    )
    _require_revision(profile.revision, body.expected_revision)
    now = datetime.now(tz=UTC)
    profile.status = body.status
    profile.suspended_at = now if body.status == "suspended" else None
    profile.activated_at = profile.activated_at or (now if body.status == "active" else None)
    profile.access_generation += 1
    profile.revision += 1
    profile.updated_by_user_id = current_user.id
    profile.updated_at = now
    user.is_active = body.status == "active"
    user.updated_at = now
    if body.status == "suspended":
        await _revoke_mobile_sessions(session, tenant_id, user.id, "account_suspended")
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action=(
            "gc_app.client_manager_suspended"
            if body.status == "suspended"
            else "gc_app.client_manager_activated"
        ),
        entity_type="client_manager_profile",
        entity_id=profile.id,
        metadata=None,
    )
    assigned_groups = (await _manager_group_map(session, [profile.id])).get(profile.id, [])
    return _client_manager_response(profile, user, organization, assigned_groups)


@router.patch(
    "/client-managers/{profile_id}/force-password-change",
    response_model=ClientManagerResponse,
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def force_client_manager_password_change(
    profile_id: uuid.UUID,
    body: ClientManagerForcePasswordChangeRequest,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ClientManagerResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    profile, user, organization = await _get_client_manager(
        session, tenant_id, profile_id, lock=True
    )
    _require_revision(profile.revision, body.expected_revision)
    # Compatibility endpoint for a rolling dashboard deployment. The forced
    # first-login flow has been retired, so even an older client asking to turn
    # it on receives the authoritative disabled state.
    profile.force_password_change = False
    profile.access_generation += 1
    profile.revision += 1
    profile.updated_by_user_id = current_user.id
    profile.updated_at = datetime.now(tz=UTC)
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action="gc_app.client_manager_force_password_change_updated",
        entity_type="client_manager_profile",
        entity_id=profile.id,
        metadata={"requested": body.force_password_change, "required": False},
    )
    assigned_groups = (await _manager_group_map(session, [profile.id])).get(profile.id, [])
    return _client_manager_response(profile, user, organization, assigned_groups)


@router.delete(
    "/client-managers/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def delete_client_manager(
    profile_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    tenant_id = _tenant_id(current_user, agency_id)
    profile, user, _organization = await _get_client_manager(
        session, tenant_id, profile_id, lock=True
    )
    now = datetime.now(tz=UTC)
    await session.execute(
        update(ClientManagerGroupAssignmentModel)
        .where(
            ClientManagerGroupAssignmentModel.profile_id == profile.id,
            ClientManagerGroupAssignmentModel.is_active.is_(True),
        )
        .values(
            is_active=False,
            revoked_by_user_id=current_user.id,
            revoked_at=now,
            updated_at=now,
        )
    )
    await _revoke_mobile_sessions(session, tenant_id, user.id, "account_deleted")
    profile.status = "deleted"
    profile.deleted_at = now
    profile.access_generation += 1
    profile.revision += 1
    profile.invitation_token_hash = None
    profile.invitation_expires_at = None
    profile.updated_by_user_id = current_user.id
    profile.updated_at = now
    user.is_active = False
    user.email = f"deleted-{user.id}@deleted.invalid"
    user.hashed_password = await run_password_work(hash_password, f"Gc1{secrets.token_urlsafe(48)}")
    user.deleted_at = now
    user.updated_at = now
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action="gc_app.client_manager_deleted",
        entity_type="client_manager_profile",
        entity_id=profile.id,
        metadata=None,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
