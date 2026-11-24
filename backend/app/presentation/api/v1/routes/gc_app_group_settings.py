"""GC group access, feature settings and passenger identity refresh routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.assignment import assign_group_company
from app.application.mobile.group_app_availability import (
    group_can_enable_mobile_access,
)
from app.application.mobile.passenger_identity_reconciliation import (
    PassengerIdentityReconciliationResult,
    reconcile_passenger_identities,
)
from app.application.mobile.sync_journal import (
    append_mobile_sync_change,
    current_role_access_operation,
)
from app.domain.entities.entities import User
from app.infrastructure.database.gc_mobile_models import (
    GCCommonDocumentModel,
    GCGroupAccessModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.mobile_group_capacity import (
    SqlAlchemyGroupPassengerCapacityGuard,
)
from app.presentation.api.v1.routes import (
    gc_app_group_access_support as _group_access_support,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    GC_ADMIN_ROLES,
    MobileAudience,
    _audit,
    _get_group,
    _get_group_access,
    _tenant_id,
)
from app.presentation.api.v1.routes.gc_app_sessions import (
    _revoke_group_mobile_sessions,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCGroupAccessResponse,
    GCGroupAccessUpdateRequest,
    GCMyPhotosFeatureUpdateRequest,
    PassengerIdentityReconciliationResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.get("/groups/{group_id}", response_model=GCGroupAccessResponse)
async def get_gc_group_access(
    group_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GCGroupAccessResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    access = await _get_group_access(
        session,
        tenant_id,
        group_id,
        lock=False,
        include_removed=True,
    )
    return await _group_access_response(session, access)


@router.put(
    "/groups/{group_id}",
    response_model=GCGroupAccessResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def configure_gc_group_access(
    group_id: uuid.UUID,
    body: GCGroupAccessUpdateRequest,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GCGroupAccessResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    group = await _get_group(session, tenant_id, group_id, lock=True)
    can_enable = group_can_enable_mobile_access(group)
    if body.enabled and not can_enable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived or deleted groups cannot be enabled in GC App",
        )
    if body.enabled:
        # The group row is already locked above, so the same configured quota
        # is checked atomically before mobile access and identity fan-out begin.
        await SqlAlchemyGroupPassengerCapacityGuard(session).assert_available(
            agency_id=tenant_id,
            group_id=group_id,
            additional_passengers=0,
        )

    access = (
        await session.execute(
            select(GCGroupAccessModel)
            .where(
                GCGroupAccessModel.agency_id == tenant_id,
                GCGroupAccessModel.group_id == group_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
    ).scalar_one_or_none()
    restoring, organization_id, company_changed = _group_access_support.validate_group_access_edit(
        group,
        access,
        body,
        can_enable=can_enable,
    )
    if company_changed:
        group = await assign_group_company(
            session,
            user=current_user,
            agency_id=tenant_id,
            group_id=group_id,
            company_id=organization_id,
            expected_revision=group.company_revision,
        )

    now = datetime.now(tz=UTC)
    revoked_roles: set[MobileAudience] = set()
    revoke_all_group_sessions = company_changed
    access_window_changed = False
    if access is None:
        access = GCGroupAccessModel(
            id=uuid.uuid4(),
            agency_id=tenant_id,
            group_id=group_id,
            client_organization_id=organization_id,
            is_enabled=body.enabled,
            passenger_access_enabled=body.passenger_access_enabled,
            client_manager_access_enabled=body.client_manager_access_enabled,
            coordinator_access_enabled=body.coordinator_access_enabled,
            access_starts_at=body.access_starts_at,
            access_expires_at=body.access_expires_at,
            revoked_at=None if body.enabled else now,
            revoked_by_user_id=None if body.enabled else current_user.id,
            access_generation=1,
            manifest_version=1,
            itinerary_version=0,
            common_document_version=0,
            announcement_version=0,
            rooming_version=0,
            meal_version=0,
            qr_version=0,
            revision=1,
            created_by_user_id=current_user.id,
            updated_by_user_id=current_user.id,
            created_at=now,
            updated_at=now,
        )
        session.add(access)
        action = "gc_app.group_added"
    else:
        if access.passenger_access_enabled and not body.passenger_access_enabled:
            revoked_roles.add("passenger")
        if access.client_manager_access_enabled and not body.client_manager_access_enabled:
            revoked_roles.add("client_manager")
        if access.coordinator_access_enabled and not body.coordinator_access_enabled:
            revoked_roles.add("coordinator")
        if access.is_enabled and not body.enabled:
            revoke_all_group_sessions = True
        if (
            access.access_starts_at != body.access_starts_at
            or access.access_expires_at != body.access_expires_at
        ):
            # A session issued under a wider time window must not preserve an
            # offline entitlement after staff narrows or changes that window.
            revoke_all_group_sessions = True
            access_window_changed = True
        access.client_organization_id = organization_id
        access.removed_at = None
        access.is_enabled = body.enabled
        access.passenger_access_enabled = body.passenger_access_enabled
        access.client_manager_access_enabled = body.client_manager_access_enabled
        access.coordinator_access_enabled = body.coordinator_access_enabled
        access.access_starts_at = body.access_starts_at
        access.access_expires_at = body.access_expires_at
        access.revoked_at = None if body.enabled else now
        access.revoked_by_user_id = None if body.enabled else current_user.id
        access.access_generation += 1
        access.manifest_version += 1
        access.revision += 1
        access.updated_by_user_id = current_user.id
        access.updated_at = now
        action = (
            "gc_app.group_restored"
            if restoring
            else ("gc_app.group_enabled" if body.enabled else "gc_app.group_disabled")
        )

    if access_window_changed:
        await session.execute(
            update(GCCommonDocumentModel)
            .where(
                GCCommonDocumentModel.gc_group_access_id == access.id,
                GCCommonDocumentModel.status.in_(("draft", "published")),
            )
            .values(
                availability_starts_at=body.access_starts_at,
                availability_expires_at=body.access_expires_at,
                updated_at=now,
            )
        )
        access.common_document_version += 1

    revoked_roles = _group_access_support.session_roles_to_revoke(
        revoked_roles,
        revoke_all_group_sessions,
        restoring=restoring,
    )
    if revoked_roles:
        await _revoke_group_mobile_sessions(
            session,
            access,
            subject_roles=revoked_roles,
            reason="group_access_policy_changed",
        )
    await session.flush()
    identity_result: PassengerIdentityReconciliationResult | None = None
    if body.enabled and body.passenger_access_enabled:
        identity_result = await reconcile_passenger_identities(
            session,
            access=access,
            actor_user_id=current_user.id,
        )
    await append_mobile_sync_change(
        session,
        access=access,
        entity_type="group_access",
        entity_id=access.id,
        operation="upsert" if body.enabled else "revoke",
        version=access.manifest_version,
        changed_by_user_id=current_user.id,
        payload={
            "resource_path": f"/api/v1/mobile/trips/{group_id}/manifest",
            "purge_required": not body.enabled,
            "revoked_roles": sorted(revoked_roles),
            "access_expires_at": (
                body.access_expires_at.isoformat() if body.access_expires_at is not None else None
            ),
        },
    )
    for revoked_role in sorted(revoked_roles):
        # A new session may still access this role after a window/owner change.
        operation = current_role_access_operation(access, revoked_role)
        await append_mobile_sync_change(
            session,
            access=access,
            audience=revoked_role,
            entity_type="role_access",
            entity_id=access.id,
            operation=operation,
            version=access.manifest_version,
            changed_by_user_id=current_user.id,
            payload={
                "resource_path": f"/api/v1/mobile/trips/{group_id}/manifest",
                "purge_required": operation == "revoke",
                "role": revoked_role,
            },
        )
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action=action,
        entity_type="gc_group_access",
        entity_id=access.id,
        metadata={
            "group_id": str(group_id),
            "enabled": body.enabled,
            "access_generation": access.access_generation,
            "passenger_identity_reconciliation": (
                {
                    "created": identity_result.created,
                    "updated": identity_result.updated,
                    "unchanged": identity_result.unchanged,
                    "revoked": identity_result.revoked,
                    "skipped_ambiguous": identity_result.skipped_ambiguous,
                    "skipped_without_secondary_factor": (
                        identity_result.skipped_without_secondary_factor
                    ),
                }
                if identity_result is not None
                else None
            ),
        },
    )
    return await _group_access_response(session, access)


@router.put(
    "/groups/{group_id}/features/my-photos",
    response_model=GCGroupAccessResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def configure_gc_group_my_photos_feature(
    group_id: uuid.UUID,
    body: GCMyPhotosFeatureUpdateRequest,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GCGroupAccessResponse:
    """Toggle the passenger My Photos capability without re-fencing sessions."""

    tenant_id = _tenant_id(current_user, agency_id)
    group = await _get_group(session, tenant_id, group_id, lock=True)
    access = await _get_group_access(session, tenant_id, group_id, lock=True)
    return await _group_access_support.configure_my_photos_feature(
        session=session,
        group=group,
        access=access,
        body=body,
        request=request,
        current_user_id=current_user.id,
        current_user=current_user,
        tenant_id=tenant_id,
        append_change=append_mobile_sync_change,
        audit_change=_audit,
        response_builder=_group_access_response,
    )


@router.post(
    "/groups/{group_id}/passenger-identities/reconcile",
    response_model=PassengerIdentityReconciliationResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def refresh_mobile_passenger_identities(
    group_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> PassengerIdentityReconciliationResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    await _get_group(session, tenant_id, group_id, lock=True)
    access = await _get_group_access(session, tenant_id, group_id, lock=True)
    if not access.is_enabled or not access.passenger_access_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Enable passenger access before refreshing passenger identities",
        )
    result = await reconcile_passenger_identities(
        session,
        access=access,
        actor_user_id=current_user.id,
    )
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action="gc_app.passenger_identities_reconciled",
        entity_type="gc_group_access",
        entity_id=access.id,
        metadata={
            "group_id": str(group_id),
            "created": result.created,
            "updated": result.updated,
            "unchanged": result.unchanged,
            "revoked": result.revoked,
            "skipped_ambiguous": result.skipped_ambiguous,
            "skipped_without_secondary_factor": (result.skipped_without_secondary_factor),
        },
    )
    return PassengerIdentityReconciliationResponse(
        created=result.created,
        updated=result.updated,
        unchanged=result.unchanged,
        revoked=result.revoked,
        skipped_ambiguous=result.skipped_ambiguous,
        skipped_without_secondary_factor=result.skipped_without_secondary_factor,
    )


async def _group_access_response(
    session: AsyncSession, access: GCGroupAccessModel
) -> GCGroupAccessResponse:
    return await _group_access_support.group_access_response(session, access)
