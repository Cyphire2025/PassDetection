"""Client-manager invitation rotation, group assignments and session fencing."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.mobile_jwt import hash_mobile_lookup
from app.core.security.password import hash_password, run_password_work
from app.domain.entities.entities import User
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.gc_app_manager_support import (
    _manager_group_map,
    _validate_manager_groups,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    GC_ADMIN_ROLES,
    _audit,
    _client_manager_response,
    _get_client_manager,
    _require_revision,
    _tenant_id,
)
from app.presentation.api.v1.routes.gc_app_sessions import (
    _revoke_mobile_sessions,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerAssignmentRequest,
    ClientManagerPasswordResetRequest,
    ClientManagerResponse,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/client-managers/{profile_id}/reset-password",
    response_model=ClientManagerResponse,
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def reset_client_manager_password(
    profile_id: uuid.UUID,
    body: ClientManagerPasswordResetRequest,
    request: Request,
    http_response: Response,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ClientManagerResponse:
    del body
    tenant_id = _tenant_id(current_user, agency_id)
    profile, user, organization = await _get_client_manager(
        session, tenant_id, profile_id, lock=True
    )
    temporary_password = f"Gc1{secrets.token_urlsafe(32)}"
    activation_token = secrets.token_urlsafe(32)
    try:
        user.hashed_password = await run_password_work(hash_password, temporary_password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    now = datetime.now(tz=UTC)
    profile.force_password_change = False
    profile.status = "invited"
    profile.activated_at = None
    profile.suspended_at = None
    profile.invitation_token_hash = hash_mobile_lookup(
        activation_token,
        purpose="manager-invitation",
    )
    profile.invitation_expires_at = now + timedelta(days=7)
    profile.access_generation += 1
    profile.revision += 1
    profile.updated_by_user_id = current_user.id
    profile.updated_at = now
    user.updated_at = now
    await _revoke_mobile_sessions(session, tenant_id, user.id, "password_reset")
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action="gc_app.client_manager_reinvited",
        entity_type="client_manager_profile",
        entity_id=profile.id,
        metadata={"sessions_revoked": True},
    )
    assigned_groups = (await _manager_group_map(session, [profile.id])).get(profile.id, [])
    response = _client_manager_response(profile, user, organization, assigned_groups)
    response.activation_token = activation_token
    http_response.headers["Cache-Control"] = "private, no-store, max-age=0"
    http_response.headers["Pragma"] = "no-cache"
    await session.commit()
    return response


@router.put(
    "/client-managers/{profile_id}/groups",
    response_model=ClientManagerResponse,
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def replace_client_manager_groups(
    profile_id: uuid.UUID,
    body: ClientManagerAssignmentRequest,
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
    requested_ids = list(dict.fromkeys(body.group_ids))
    access_by_group = await _validate_manager_groups(
        session, tenant_id, profile.organization_id, requested_ids
    )
    now = datetime.now(tz=UTC)
    existing = list(
        (
            await session.execute(
                select(ClientManagerGroupAssignmentModel)
                .where(ClientManagerGroupAssignmentModel.profile_id == profile.id)
                .with_for_update()
            )
        ).scalars()
    )
    by_group = {item.group_id: item for item in existing}
    for assignment in existing:
        if assignment.group_id not in access_by_group and assignment.is_active:
            assignment.is_active = False
            assignment.revoked_by_user_id = current_user.id
            assignment.revoked_at = now
            assignment.updated_at = now
    for group_id, access in access_by_group.items():
        current_assignment = by_group.get(group_id)
        if current_assignment is None:
            session.add(
                ClientManagerGroupAssignmentModel(
                    id=uuid.uuid4(),
                    agency_id=tenant_id,
                    organization_id=profile.organization_id,
                    group_id=group_id,
                    profile_id=profile.id,
                    gc_group_access_id=access.id,
                    is_active=True,
                    can_view_passenger_names=False,
                    personal_document_access_enabled=False,
                    assigned_by_user_id=current_user.id,
                    assigned_at=now,
                    updated_at=now,
                )
            )
        else:
            if current_assignment.organization_id != profile.organization_id:
                current_assignment.can_view_passenger_names = False
                current_assignment.personal_document_access_enabled = False
            current_assignment.organization_id = profile.organization_id
            current_assignment.gc_group_access_id = access.id
            current_assignment.is_active = True
            current_assignment.revoked_by_user_id = None
            current_assignment.revoked_at = None
            current_assignment.assigned_by_user_id = current_user.id
            current_assignment.assigned_at = now
            current_assignment.updated_at = now
    profile.access_generation += 1
    profile.revision += 1
    profile.updated_by_user_id = current_user.id
    profile.updated_at = now
    await _revoke_mobile_sessions(session, tenant_id, user.id, "group_assignments_changed")
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action="gc_app.client_manager_groups_replaced",
        entity_type="client_manager_profile",
        entity_id=profile.id,
        metadata={"group_count": len(access_by_group)},
    )
    assigned_groups = (await _manager_group_map(session, [profile.id])).get(profile.id, [])
    return _client_manager_response(profile, user, organization, assigned_groups)


@router.post(
    "/client-managers/{profile_id}/revoke-sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def revoke_client_manager_sessions(
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
    profile.access_generation += 1
    profile.revision += 1
    profile.updated_by_user_id = current_user.id
    profile.updated_at = datetime.now(tz=UTC)
    await _revoke_mobile_sessions(session, tenant_id, user.id, "admin_revoked_all")
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action="gc_app.client_manager_sessions_revoked",
        entity_type="client_manager_profile",
        entity_id=profile.id,
        metadata=None,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
