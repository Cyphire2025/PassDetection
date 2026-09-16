"""Remove a GC App setup while retaining its source records and send history."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.sync_journal import append_mobile_sync_change
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.gc_app import (
    GC_ADMIN_ROLES,
    _audit,
    _get_group,
    _get_group_access,
    _revoke_group_mobile_sessions,
    _tenant_id,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.delete(
    "/groups/{group_id}", status_code=204, dependencies=[Depends(require_cookie_csrf)]
)
async def emergency_revoke_gc_group_access(
    group_id: uuid.UUID,
    request: Request,
    expected_revision: int | None = Query(default=None, ge=1),
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Keep explicit emergency session invalidation separate from list removal."""
    tenant_id = _tenant_id(current_user, agency_id)
    await _get_group(session, tenant_id, group_id, lock=True)
    access = await _get_group_access(session, tenant_id, group_id, lock=True)
    if expected_revision is not None and access.revision != expected_revision:
        raise HTTPException(status_code=409, detail="GC App settings changed; refresh and retry")
    now = datetime.now(UTC)
    access.is_enabled = False
    access.passenger_access_enabled = False
    access.client_manager_access_enabled = False
    access.coordinator_access_enabled = False
    access.revoked_at = now
    access.revoked_by_user_id = current_user.id
    access.access_generation += 1
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    roles = {"passenger", "client_manager", "coordinator"}
    await _revoke_group_mobile_sessions(
        session, access, subject_roles={"passenger", "client_manager", "coordinator"},
        reason="group_access_revoked",
    )
    await append_mobile_sync_change(
        session, access=access, entity_type="group_access", entity_id=access.id,
        operation="revoke", version=access.manifest_version,
        changed_by_user_id=current_user.id,
        payload={
            "resource_path": f"/api/v1/mobile/trips/{group_id}/manifest",
            "purge_required": True, "revoked_roles": sorted(roles),
        },
    )
    for role in ("passenger", "client_manager", "coordinator"):
        await append_mobile_sync_change(
            session, access=access, audience=role, entity_type="role_access",
            entity_id=access.id, operation="revoke", version=access.manifest_version,
            changed_by_user_id=current_user.id,
            payload={
                "resource_path": f"/api/v1/mobile/trips/{group_id}/manifest",
                "purge_required": True, "role": role,
            },
        )
    await _audit(
        session, current_user, request, agency_id=tenant_id,
        action="gc_app.group_revoked", entity_type="gc_group_access", entity_id=access.id,
        metadata={"group_id": str(group_id), "access_generation": access.access_generation},
    )
    await session.commit()
    return Response(status_code=204)


@router.delete(
    "/groups/{group_id}/app-setup", status_code=204, dependencies=[Depends(require_cookie_csrf)]
)
async def remove_gc_group_access(
    group_id: uuid.UUID,
    request: Request,
    expected_revision: int = Query(ge=1),
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    tenant_id = _tenant_id(current_user, agency_id)
    # Match the Add/settings path's lock order, including archived/deleted
    # source groups. Nothing below deletes or edits the source group itself.
    await _get_group(session, tenant_id, group_id, lock=True)
    access = await _get_group_access(session, tenant_id, group_id, lock=True, include_removed=True)
    if access.revision != expected_revision:
        raise HTTPException(status_code=409, detail="GC App settings changed; refresh and retry")
    if access.removed_at is not None:
        await session.commit()
        return Response(status_code=204)

    now = datetime.now(UTC)
    access.removed_at = now
    access.is_enabled = False
    access.revoked_at = now
    access.revoked_by_user_id = current_user.id
    access.access_generation += 1
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    # Fence this trip's grants, not the account's sessions: one passenger or
    # coordinator may legitimately retain access to several unrelated trips.
    await append_mobile_sync_change(
        session, access=access, entity_type="group_access", entity_id=access.id,
        operation="revoke", version=access.manifest_version,
        changed_by_user_id=current_user.id,
        payload={
            "resource_path": f"/api/v1/mobile/trips/{group_id}/manifest",
            "purge_required": True,
            "reason": "removed_from_gc_app",
            "revoked_roles": ["client_manager", "coordinator", "passenger"],
        },
    )
    await _audit(
        session, current_user, request, agency_id=tenant_id,
        action="gc_app.group_removed", entity_type="gc_group_access", entity_id=access.id,
        metadata={"group_id": str(group_id), "access_generation": access.access_generation},
    )
    # A success response acknowledges a durable removal, including its audit
    # and journal entry. The outer dependency still handles rollback on error.
    await session.commit()
    return Response(status_code=204)
