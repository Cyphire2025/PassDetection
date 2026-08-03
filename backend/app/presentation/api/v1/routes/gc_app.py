"""Dashboard administration for GC App accounts, access, and publication."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_identity_reconciliation import (
    PassengerIdentityReconciliationResult,
    reconcile_passenger_identities,
)
from app.application.mobile.sync_journal import append_mobile_sync_change
from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.core.security.mobile_jwt import hash_mobile_lookup
from app.core.security.password import hash_password
from app.domain.entities.entities import GroupStatus, User, UserRole
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    ClientOrganizationModel,
    GCCommonDocumentModel,
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobilePassengerIdentityModel,
    MobileRefreshTokenModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerAssignedGroupResponse,
    ClientManagerAssignmentRequest,
    ClientManagerCreateRequest,
    ClientManagerForcePasswordChangeRequest,
    ClientManagerPageResponse,
    ClientManagerPasswordResetRequest,
    ClientManagerResponse,
    ClientManagerSessionResponse,
    ClientManagerStatusRequest,
    ClientManagerUpdateRequest,
    ClientOrganizationCreateRequest,
    ClientOrganizationPageResponse,
    ClientOrganizationResponse,
    GCAgencyPageResponse,
    GCAgencyResponse,
    GCAppAuditResponse,
    GCGroupAccessResponse,
    GCGroupAccessUpdateRequest,
    GCGroupSearchAccess,
    GCGroupSearchItem,
    GCGroupSearchPageResponse,
    PassengerIdentityReconciliationResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()
GC_ADMIN_ROLES = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER]


@router.get("/agencies", response_model=GCAgencyPageResponse)
async def list_gc_agencies(
    q: str | None = Query(default=None, max_length=120),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GCAgencyPageResponse:
    """Return a bounded tenant selector without granting cross-tenant access."""

    filters = [AgencyModel.is_active.is_(True)]
    if current_user.role != UserRole.SUPER_ADMIN:
        if current_user.agency_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The account is not assigned to an agency",
            )
        filters.append(AgencyModel.id == current_user.agency_id)
    if q and (normalized := " ".join(q.split())):
        filters.append(
            AgencyModel.name.contains(normalized, autoescape=True)
            | AgencyModel.email.contains(normalized, autoescape=True)
        )
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(AgencyModel).where(*filters)
            )
        ).scalar_one()
    )
    agencies = list(
        (
            await session.execute(
                select(AgencyModel)
                .where(*filters)
                .order_by(AgencyModel.name.asc(), AgencyModel.id.asc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return GCAgencyPageResponse(
        items=[
            GCAgencyResponse(
                id=agency.id,
                name=agency.name,
                email=agency.email,
                is_active=agency.is_active,
            )
            for agency in agencies
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/groups", response_model=GCGroupSearchPageResponse)
async def search_gc_groups(
    q: str | None = Query(default=None, max_length=120),
    agency_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    gc_enabled: bool | None = None,
    eligible_only: bool = False,
    lifecycle_status: str | None = Query(default=None, max_length=16),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GCGroupSearchPageResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    filters = [ClientGroupModel.agency_id == tenant_id]
    if group_id is not None:
        filters.append(ClientGroupModel.id == group_id)
    if lifecycle_status is not None:
        if lifecycle_status not in {item.value for item in GroupStatus}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid group lifecycle status",
            )
        filters.append(ClientGroupModel.status == lifecycle_status)
    if q and (normalized := " ".join(q.split())):
        filters.append(
            or_(
                ClientGroupModel.name.icontains(normalized, autoescape=True),
                ClientGroupModel.destination.icontains(normalized, autoescape=True),
            )
        )
    access_join = (
        (GCGroupAccessModel.group_id == ClientGroupModel.id)
        & (GCGroupAccessModel.agency_id == ClientGroupModel.agency_id)
    )
    if eligible_only:
        filters.extend(
            [
                ClientGroupModel.status == GroupStatus.ACTIVE.value,
                or_(
                    GCGroupAccessModel.id.is_(None),
                    GCGroupAccessModel.is_enabled.is_(False),
                    GCGroupAccessModel.revoked_at.is_not(None),
                ),
            ]
        )
    elif gc_enabled is True:
        filters.extend(
            [
                GCGroupAccessModel.is_enabled.is_(True),
                GCGroupAccessModel.revoked_at.is_(None),
            ]
        )
    elif gc_enabled is False:
        filters.append(
            or_(
                GCGroupAccessModel.id.is_(None),
                GCGroupAccessModel.is_enabled.is_(False),
                GCGroupAccessModel.revoked_at.is_not(None),
            )
        )
    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ClientGroupModel)
                .outerjoin(GCGroupAccessModel, access_join)
                .where(*filters)
            )
        ).scalar_one()
    )
    # Enabled-group pages need usage metrics, but candidate searches do not.
    # Aggregate once for the whole page instead of issuing two count queries
    # per group.  The account count and acknowledged-device count deliberately
    # have different semantics and therefore must not reuse one session count.
    include_metrics = gc_enabled is True or group_id is not None
    usage_metrics = None
    if include_metrics:
        now = datetime.now(tz=UTC)
        usage_metrics = (
            select(
                MobileDeviceSessionModel.selected_gc_group_access_id.label(
                    "gc_group_access_id"
                ),
                func.count(func.distinct(MobileDeviceSessionModel.account_id)).label(
                    "active_mobile_users"
                ),
                func.count(
                    func.distinct(MobileDeviceSessionModel.device_identifier_hash)
                )
                .filter(
                    MobileDeviceSessionModel.last_sync_acknowledged_at.is_not(None)
                )
                .label("synced_device_count"),
            )
            .where(
                MobileDeviceSessionModel.agency_id == tenant_id,
                MobileDeviceSessionModel.selected_gc_group_access_id.is_not(None),
                MobileDeviceSessionModel.status == "active",
                MobileDeviceSessionModel.revoked_at.is_(None),
                MobileDeviceSessionModel.expires_at > now,
            )
            .group_by(MobileDeviceSessionModel.selected_gc_group_access_id)
            .subquery()
        )

    result_columns = [
        ClientGroupModel,
        GCGroupAccessModel,
        ClientOrganizationModel,
    ]
    if usage_metrics is not None:
        result_columns.extend(
            [
                usage_metrics.c.active_mobile_users,
                usage_metrics.c.synced_device_count,
            ]
        )
    statement = (
        select(*result_columns)
            .outerjoin(
                GCGroupAccessModel,
                access_join,
            )
            .outerjoin(
                ClientOrganizationModel,
                (ClientOrganizationModel.id == GCGroupAccessModel.client_organization_id)
                & (ClientOrganizationModel.agency_id == ClientGroupModel.agency_id),
            )
            .where(*filters)
            .order_by(ClientGroupModel.created_at.desc(), ClientGroupModel.id.desc())
            .offset(offset)
            .limit(limit)
    )
    if usage_metrics is not None:
        statement = statement.outerjoin(
            usage_metrics,
            usage_metrics.c.gc_group_access_id == GCGroupAccessModel.id,
        )
    rows = (await session.execute(statement)).all()

    items: list[GCGroupSearchItem] = []
    for row in rows:
        group, access, organization = row[0], row[1], row[2]
        active_mobile_users = int(row[3] or 0) if usage_metrics is not None else 0
        synced_device_count = int(row[4] or 0) if usage_metrics is not None else 0
        items.append(
            GCGroupSearchItem(
                id=group.id,
                agency_id=group.agency_id,
                name=group.name,
                destination=group.destination,
                travel_date=group.travel_date,
                return_date=group.return_date,
                lifecycle_status=group.status,
                gc_enabled=bool(
                    access and access.is_enabled and access.revoked_at is None
                ),
                client_organization_id=(
                    access.client_organization_id if access is not None else None
                ),
                client_organization_name=(organization.name if organization else None),
                access=(
                    GCGroupSearchAccess(
                        group_id=group.id,
                        agency_id=group.agency_id,
                        client_organization_id=access.client_organization_id,
                        client_organization_name=organization.name,
                        enabled=access.is_enabled,
                        passenger_access_enabled=access.passenger_access_enabled,
                        client_manager_access_enabled=access.client_manager_access_enabled,
                        coordinator_access_enabled=access.coordinator_access_enabled,
                        access_starts_at=access.access_starts_at,
                        access_expires_at=access.access_expires_at,
                        revoked_at=access.revoked_at,
                        access_generation=access.access_generation,
                        itinerary_version=access.itinerary_version,
                        common_document_version=access.common_document_version,
                        announcement_version=access.announcement_version,
                        revision=access.revision,
                        last_successful_sync_at=access.last_successful_sync_at,
                        active_mobile_users=active_mobile_users,
                        synced_device_count=synced_device_count,
                        updated_at=access.updated_at,
                    )
                    if access is not None and organization is not None
                    else None
                ),
            )
        )

    return GCGroupSearchPageResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/groups/{group_id}", response_model=GCGroupAccessResponse)
async def get_gc_group_access(
    group_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GCGroupAccessResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    access = await _get_group_access(session, tenant_id, group_id, lock=False)
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
    if body.enabled and group.status not in {
        GroupStatus.ACTIVE.value,
        GroupStatus.CLOSED.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived or deleted groups cannot be enabled in GC App",
        )

    access = (
        await session.execute(
            select(GCGroupAccessModel)
            .where(
                GCGroupAccessModel.agency_id == tenant_id,
                GCGroupAccessModel.group_id == group_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    organization_id = body.client_organization_id or (
        access.client_organization_id if access else None
    )
    if organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A client organization is required when adding a group to GC App",
        )
    await _get_organization(session, tenant_id, organization_id, lock=True)

    now = datetime.now(tz=UTC)
    revoked_roles: set[str] = set()
    revoke_all_group_sessions = False
    access_window_changed = False
    if access is None:
        if group.status != GroupStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only an active group can be added to GC App",
            )
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
        if body.expected_revision is None or body.expected_revision != access.revision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="GC App settings changed; refresh and retry",
            )
        if organization_id != access.client_organization_id:
            active_assignments = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(ClientManagerGroupAssignmentModel)
                        .where(
                            ClientManagerGroupAssignmentModel.gc_group_access_id == access.id,
                            ClientManagerGroupAssignmentModel.is_active.is_(True),
                        )
                    )
                ).scalar_one()
            )
            if active_assignments:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Remove Client Manager assignments before changing the client organization",
                )
            revoke_all_group_sessions = True
        if access.passenger_access_enabled and not body.passenger_access_enabled:
            revoked_roles.add("passenger")
        if (
            access.client_manager_access_enabled
            and not body.client_manager_access_enabled
        ):
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
        action = "gc_app.group_enabled" if body.enabled else "gc_app.group_disabled"

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

    if revoke_all_group_sessions:
        revoked_roles = {"passenger", "client_manager", "coordinator"}
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
                body.access_expires_at.isoformat()
                if body.access_expires_at is not None
                else None
            ),
        },
    )
    for revoked_role in sorted(revoked_roles):
        await append_mobile_sync_change(
            session,
            access=access,
            audience=revoked_role,
            entity_type="role_access",
            entity_id=access.id,
            operation="revoke",
            version=access.manifest_version,
            changed_by_user_id=current_user.id,
            payload={
                "resource_path": f"/api/v1/mobile/trips/{group_id}/manifest",
                "purge_required": True,
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
            "skipped_without_secondary_factor": (
                result.skipped_without_secondary_factor
            ),
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


@router.delete(
    "/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_cookie_csrf)],
)
async def revoke_gc_group_access(
    group_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    tenant_id = _tenant_id(current_user, agency_id)
    access = await _get_group_access(session, tenant_id, group_id, lock=True)
    now = datetime.now(tz=UTC)
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
    revoked_roles = {"passenger", "client_manager", "coordinator"}
    await _revoke_group_mobile_sessions(
        session,
        access,
        subject_roles=revoked_roles,
        reason="group_access_revoked",
    )
    await append_mobile_sync_change(
        session,
        access=access,
        entity_type="group_access",
        entity_id=access.id,
        operation="revoke",
        version=access.manifest_version,
        changed_by_user_id=current_user.id,
        payload={
            "resource_path": f"/api/v1/mobile/trips/{group_id}/manifest",
            "purge_required": True,
            "revoked_roles": sorted(revoked_roles),
        },
    )
    for revoked_role in sorted(revoked_roles):
        await append_mobile_sync_change(
            session,
            access=access,
            audience=revoked_role,
            entity_type="role_access",
            entity_id=access.id,
            operation="revoke",
            version=access.manifest_version,
            changed_by_user_id=current_user.id,
            payload={
                "resource_path": f"/api/v1/mobile/trips/{group_id}/manifest",
                "purge_required": True,
                "role": revoked_role,
            },
        )
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action="gc_app.group_revoked",
        entity_type="gc_group_access",
        entity_id=access.id,
        metadata={"group_id": str(group_id), "access_generation": access.access_generation},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
        filters.append(
            ClientOrganizationModel.name.icontains(normalized, autoescape=True)
        )
    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ClientOrganizationModel)
                .where(*filters)
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
    tenant_id = _tenant_id(current_user, agency_id)
    normalized_name = body.name.casefold()
    existing = (
        await session.execute(
            select(ClientOrganizationModel.id).where(
                ClientOrganizationModel.agency_id == tenant_id,
                ClientOrganizationModel.normalized_name == normalized_name,
                ClientOrganizationModel.status != "deleted",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Organization already exists")
    now = datetime.now(tz=UTC)
    organization = ClientOrganizationModel(
        id=uuid.uuid4(),
        agency_id=tenant_id,
        name=body.name,
        normalized_name=normalized_name,
        status="active",
        created_by_user_id=current_user.id,
        updated_by_user_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    session.add(organization)
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action="gc_app.organization_created",
        entity_type="client_organization",
        entity_id=organization.id,
        metadata=None,
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
    organization = await _get_organization(
        session,
        tenant_id,
        organization_id,
        lock=True,
    )
    enabled_group_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(GCGroupAccessModel)
                .where(
                    GCGroupAccessModel.agency_id == tenant_id,
                    GCGroupAccessModel.client_organization_id == organization.id,
                    GCGroupAccessModel.is_enabled.is_(True),
                    GCGroupAccessModel.revoked_at.is_(None),
                )
            )
        ).scalar_one()
    )
    live_manager_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ClientManagerProfileModel)
                .where(
                    ClientManagerProfileModel.agency_id == tenant_id,
                    ClientManagerProfileModel.organization_id == organization.id,
                    ClientManagerProfileModel.status != "deleted",
                )
            )
        ).scalar_one()
    )
    if enabled_group_count or live_manager_count:
        dependencies: list[str] = []
        if enabled_group_count:
            dependencies.append(
                f"{enabled_group_count} enabled GC App group"
                f"{'s' if enabled_group_count != 1 else ''}"
            )
        if live_manager_count:
            dependencies.append(
                f"{live_manager_count} Client Manager account"
                f"{'s' if live_manager_count != 1 else ''}"
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This company/client cannot be removed while it is used by "
                + " and ".join(dependencies)
                + ". Remove those assignments first."
            ),
        )

    now = datetime.now(tz=UTC)
    organization.status = "deleted"
    organization.deleted_at = now
    organization.updated_by_user_id = current_user.id
    organization.updated_at = now
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action="gc_app.organization_deleted",
        entity_type="client_organization",
        entity_id=organization.id,
        metadata={
            "historical_group_references_retained": True,
            "historical_manager_references_retained": True,
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/client-managers", response_model=ClientManagerPageResponse)
async def list_client_managers(
    q: str | None = Query(default=None, max_length=120),
    agency_id: uuid.UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ClientManagerPageResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    filters = [
        ClientManagerProfileModel.agency_id == tenant_id,
        ClientManagerProfileModel.deleted_at.is_(None),
        UserModel.role == UserRole.CLIENT_MANAGER.value,
    ]
    if q and (normalized := " ".join(q.split())):
        filters.append(
            UserModel.full_name.contains(normalized, autoescape=True)
            | UserModel.email.contains(normalized, autoescape=True)
        )
    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ClientManagerProfileModel)
                .join(UserModel, UserModel.id == ClientManagerProfileModel.user_id)
                .where(*filters)
            )
        ).scalar_one()
    )
    rows = (
        await session.execute(
            select(ClientManagerProfileModel, UserModel, ClientOrganizationModel)
            .join(UserModel, UserModel.id == ClientManagerProfileModel.user_id)
            .join(
                ClientOrganizationModel,
                ClientOrganizationModel.id == ClientManagerProfileModel.organization_id,
            )
            .where(*filters)
            .order_by(ClientManagerProfileModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    group_map = await _manager_group_map(
        session, [profile.id for profile, _user, _organization in rows]
    )
    return ClientManagerPageResponse(
        items=[
            _client_manager_response(profile, user, organization, group_map.get(profile.id, []))
            for profile, user, organization in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/client-managers",
    response_model=ClientManagerResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def create_client_manager(
    body: ClientManagerCreateRequest,
    request: Request,
    http_response: Response,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ClientManagerResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    organization = await _get_organization(session, tenant_id, body.organization_id, lock=True)
    normalized_phone = normalize_whatsapp_phone(body.phone_number)
    if normalized_phone is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Phone number is not valid for WhatsApp/mobile matching",
        )
    email = str(body.email).lower().strip()
    if (
        await session.execute(select(UserModel.id).where(UserModel.email == email))
    ).scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already in use")

    access_by_group = await _validate_manager_groups(
        session, tenant_id, organization.id, body.group_ids
    )
    temporary_password = body.temporary_password or f"Gc1{secrets.token_urlsafe(18)}"
    activation_token = secrets.token_urlsafe(32) if body.invitation_flow else None
    initial_status = (
        "invited" if activation_token is not None or body.force_password_change else "active"
    )
    try:
        password_hash = hash_password(temporary_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    now = datetime.now(tz=UTC)
    user = UserModel(
        id=uuid.uuid4(),
        email=email,
        hashed_password=password_hash,
        full_name=" ".join(body.full_name.split()),
        role=UserRole.CLIENT_MANAGER.value,
        agency_id=tenant_id,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    profile = ClientManagerProfileModel(
        id=uuid.uuid4(),
        agency_id=tenant_id,
        user_id=user.id,
        organization_id=organization.id,
        normalized_phone_number=normalized_phone,
        status=initial_status,
        force_password_change=body.force_password_change,
        invitation_token_hash=(
            hash_mobile_lookup(activation_token, purpose="manager-invitation")
            if activation_token
            else None
        ),
        invitation_expires_at=now + timedelta(days=7) if activation_token else None,
        activated_at=now if initial_status == "active" else None,
        access_generation=1,
        revision=1,
        created_by_user_id=current_user.id,
        updated_by_user_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    session.add_all([user, profile])
    await session.flush()
    for group_id, access in access_by_group.items():
        session.add(
            ClientManagerGroupAssignmentModel(
                id=uuid.uuid4(),
                agency_id=tenant_id,
                organization_id=organization.id,
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
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action="gc_app.client_manager_created",
        entity_type="client_manager_profile",
        entity_id=profile.id,
        metadata={"group_count": len(access_by_group)},
    )
    assigned_groups = (await _manager_group_map(session, [profile.id])).get(
        profile.id, []
    )
    response = _client_manager_response(
        profile, user, organization, assigned_groups
    )
    if body.return_temporary_password_once and not body.invitation_flow:
        response.temporary_password = temporary_password
    if body.return_activation_token_once and activation_token:
        response.activation_token = activation_token
    http_response.headers["Cache-Control"] = "private, no-store, max-age=0"
    http_response.headers["Pragma"] = "no-cache"
    return response


@router.patch(
    "/client-managers/{profile_id}",
    response_model=ClientManagerResponse,
    dependencies=[Depends(require_cookie_csrf)],
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
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already in use")
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
        organization = await _get_organization(
            session, tenant_id, body.organization_id, lock=True
        )
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
        profile.organization_id = organization.id
        profile.access_generation += 1
        await _revoke_mobile_sessions(
            session, tenant_id, user.id, "client_organization_changed"
        )
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
    assigned_groups = (await _manager_group_map(session, [profile.id])).get(
        profile.id, []
    )
    return _client_manager_response(profile, user, organization, assigned_groups)


@router.patch(
    "/client-managers/{profile_id}/status",
    response_model=ClientManagerResponse,
    dependencies=[Depends(require_cookie_csrf)],
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
    assigned_groups = (await _manager_group_map(session, [profile.id])).get(
        profile.id, []
    )
    return _client_manager_response(profile, user, organization, assigned_groups)


@router.post(
    "/client-managers/{profile_id}/reset-password",
    response_model=ClientManagerResponse,
    dependencies=[Depends(require_cookie_csrf)],
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
    tenant_id = _tenant_id(current_user, agency_id)
    profile, user, organization = await _get_client_manager(
        session, tenant_id, profile_id, lock=True
    )
    temporary_password = body.temporary_password or f"Gc1{secrets.token_urlsafe(18)}"
    try:
        user.hashed_password = hash_password(temporary_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    now = datetime.now(tz=UTC)
    profile.force_password_change = body.force_password_change
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
        action="gc_app.client_manager_password_reset",
        entity_type="client_manager_profile",
        entity_id=profile.id,
        metadata={"force_password_change": body.force_password_change},
    )
    assigned_groups = (await _manager_group_map(session, [profile.id])).get(
        profile.id, []
    )
    response = _client_manager_response(
        profile, user, organization, assigned_groups
    )
    if body.return_temporary_password_once:
        response.temporary_password = temporary_password
    http_response.headers["Cache-Control"] = "private, no-store, max-age=0"
    http_response.headers["Pragma"] = "no-cache"
    return response


@router.patch(
    "/client-managers/{profile_id}/force-password-change",
    response_model=ClientManagerResponse,
    dependencies=[Depends(require_cookie_csrf)],
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
    profile.force_password_change = body.force_password_change
    profile.access_generation += 1
    profile.revision += 1
    profile.updated_by_user_id = current_user.id
    profile.updated_at = datetime.now(tz=UTC)
    if body.force_password_change:
        await _revoke_mobile_sessions(
            session, tenant_id, user.id, "password_change_required"
        )
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action="gc_app.client_manager_force_password_change_updated",
        entity_type="client_manager_profile",
        entity_id=profile.id,
        metadata={"required": body.force_password_change},
    )
    assigned_groups = (await _manager_group_map(session, [profile.id])).get(
        profile.id, []
    )
    return _client_manager_response(profile, user, organization, assigned_groups)


@router.put(
    "/client-managers/{profile_id}/groups",
    response_model=ClientManagerResponse,
    dependencies=[Depends(require_cookie_csrf)],
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
        assignment = by_group.get(group_id)
        if assignment is None:
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
            assignment.gc_group_access_id = access.id
            assignment.is_active = True
            assignment.revoked_by_user_id = None
            assignment.revoked_at = None
            assignment.assigned_by_user_id = current_user.id
            assignment.assigned_at = now
            assignment.updated_at = now
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
    assigned_groups = (await _manager_group_map(session, [profile.id])).get(
        profile.id, []
    )
    return _client_manager_response(profile, user, organization, assigned_groups)


@router.post(
    "/client-managers/{profile_id}/revoke-sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_cookie_csrf)],
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


@router.get(
    "/client-managers/{profile_id}/sessions",
    response_model=list[ClientManagerSessionResponse],
)
async def list_client_manager_sessions(
    profile_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ClientManagerSessionResponse]:
    tenant_id = _tenant_id(current_user, agency_id)
    _profile, user, _organization = await _get_client_manager(
        session, tenant_id, profile_id, lock=False
    )
    items = list(
        (
            await session.execute(
                select(MobileDeviceSessionModel)
                .where(
                    MobileDeviceSessionModel.agency_id == tenant_id,
                    MobileDeviceSessionModel.user_id == user.id,
                )
                .order_by(MobileDeviceSessionModel.created_at.desc())
                .limit(100)
            )
        ).scalars()
    )
    return [
        ClientManagerSessionResponse(
            id=item.id,
            platform=item.platform,
            app_version=item.app_version,
            status=item.status,
            last_seen_at=item.last_seen_at,
            created_at=item.created_at,
            expires_at=item.expires_at,
            revoked_at=item.revoked_at,
        )
        for item in items
    ]


@router.get(
    "/client-managers/{profile_id}/audit",
    response_model=list[GCAppAuditResponse],
)
async def list_client_manager_audit(
    profile_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[GCAppAuditResponse]:
    tenant_id = _tenant_id(current_user, agency_id)
    await _get_client_manager(session, tenant_id, profile_id, lock=False)
    logs = list(
        (
            await session.execute(
                select(AuditLogModel)
                .where(
                    AuditLogModel.agency_id == tenant_id,
                    AuditLogModel.entity_type == "client_manager_profile",
                    AuditLogModel.entity_id == str(profile_id),
                )
                .order_by(AuditLogModel.created_at.desc())
                .limit(200)
            )
        ).scalars()
    )
    return [
        GCAppAuditResponse(
            id=item.id,
            action=item.action,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            actor_email=item.actor_email,
            metadata=item.metadata_json or {},
            created_at=item.created_at,
        )
        for item in logs
    ]


@router.delete(
    "/client-managers/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_cookie_csrf)],
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
    user.hashed_password = hash_password(f"Gc1{secrets.token_urlsafe(48)}")
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


def _tenant_id(current_user: User, requested: uuid.UUID | None = None) -> uuid.UUID:
    if current_user.role == UserRole.SUPER_ADMIN:
        if requested is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="agency_id is required for super-admin GC App operations",
            )
        return requested
    if current_user.agency_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The account is not assigned to an agency",
        )
    if requested is not None and requested != current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agency scope mismatch")
    return current_user.agency_id


async def _get_group(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    lock: bool,
) -> ClientGroupModel:
    stmt = select(ClientGroupModel).where(
        ClientGroupModel.id == group_id,
        ClientGroupModel.agency_id == agency_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    group = (await session.execute(stmt)).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


async def _get_group_access(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    lock: bool,
) -> GCGroupAccessModel:
    stmt = select(GCGroupAccessModel).where(
        GCGroupAccessModel.agency_id == agency_id,
        GCGroupAccessModel.group_id == group_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    access = (await session.execute(stmt)).scalar_one_or_none()
    if access is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GC App group not found")
    return access


async def _get_organization(
    session: AsyncSession,
    agency_id: uuid.UUID,
    organization_id: uuid.UUID,
    *,
    lock: bool,
) -> ClientOrganizationModel:
    stmt = select(ClientOrganizationModel).where(
        ClientOrganizationModel.id == organization_id,
        ClientOrganizationModel.agency_id == agency_id,
        ClientOrganizationModel.status == "active",
    )
    if lock:
        stmt = stmt.with_for_update()
    organization = (await session.execute(stmt)).scalar_one_or_none()
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return organization


async def _get_client_manager(
    session: AsyncSession,
    agency_id: uuid.UUID,
    profile_id: uuid.UUID,
    *,
    lock: bool,
) -> tuple[ClientManagerProfileModel, UserModel, ClientOrganizationModel]:
    stmt = (
        select(ClientManagerProfileModel, UserModel, ClientOrganizationModel)
        .join(UserModel, UserModel.id == ClientManagerProfileModel.user_id)
        .join(
            ClientOrganizationModel,
            ClientOrganizationModel.id == ClientManagerProfileModel.organization_id,
        )
        .where(
            ClientManagerProfileModel.id == profile_id,
            ClientManagerProfileModel.agency_id == agency_id,
            ClientManagerProfileModel.deleted_at.is_(None),
            UserModel.role == UserRole.CLIENT_MANAGER.value,
            UserModel.agency_id == agency_id,
        )
    )
    if lock:
        stmt = stmt.with_for_update(of=(ClientManagerProfileModel, UserModel))
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client Manager not found")
    return row


async def _validate_manager_groups(
    session: AsyncSession,
    agency_id: uuid.UUID,
    organization_id: uuid.UUID,
    group_ids: list[uuid.UUID],
) -> dict[uuid.UUID, GCGroupAccessModel]:
    unique_ids = list(dict.fromkeys(group_ids))
    if not unique_ids:
        return {}
    accesses = list(
        (
            await session.execute(
                select(GCGroupAccessModel).where(
                    GCGroupAccessModel.agency_id == agency_id,
                    GCGroupAccessModel.group_id.in_(unique_ids),
                    GCGroupAccessModel.client_organization_id == organization_id,
                )
            )
        ).scalars()
    )
    by_group = {item.group_id: item for item in accesses}
    if len(by_group) != len(unique_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Every assigned group must belong to the selected organization in GC App",
        )
    return by_group


async def _manager_group_map(
    session: AsyncSession, profile_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[ClientManagerAssignedGroupResponse]]:
    if not profile_ids:
        return {}
    rows = (
        await session.execute(
            select(
                ClientManagerGroupAssignmentModel.profile_id,
                ClientGroupModel,
                GCGroupAccessModel,
                ClientOrganizationModel,
            )
            .join(
                GCGroupAccessModel,
                GCGroupAccessModel.id
                == ClientManagerGroupAssignmentModel.gc_group_access_id,
            )
            .join(
                ClientGroupModel,
                ClientGroupModel.id == ClientManagerGroupAssignmentModel.group_id,
            )
            .join(
                ClientOrganizationModel,
                ClientOrganizationModel.id
                == ClientManagerGroupAssignmentModel.organization_id,
            )
            .where(
                ClientManagerGroupAssignmentModel.profile_id.in_(profile_ids),
                ClientManagerGroupAssignmentModel.is_active.is_(True),
                ClientManagerGroupAssignmentModel.revoked_at.is_(None),
                GCGroupAccessModel.agency_id
                == ClientManagerGroupAssignmentModel.agency_id,
                ClientGroupModel.agency_id
                == ClientManagerGroupAssignmentModel.agency_id,
                ClientOrganizationModel.agency_id
                == ClientManagerGroupAssignmentModel.agency_id,
            )
            .order_by(ClientGroupModel.travel_date.asc(), ClientGroupModel.name.asc())
        )
    ).all()
    result: dict[uuid.UUID, list[ClientManagerAssignedGroupResponse]] = {}
    for profile_id, group, access, organization in rows:
        result.setdefault(profile_id, []).append(
            ClientManagerAssignedGroupResponse(
                id=group.id,
                name=group.name,
                destination=group.destination,
                travel_date=group.travel_date,
                return_date=group.return_date,
                lifecycle_status=group.status,
                gc_enabled=access.is_enabled and access.revoked_at is None,
                client_organization_id=organization.id,
                client_organization_name=organization.name,
            )
        )
    return result


async def _revoke_mobile_sessions(
    session: AsyncSession,
    agency_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: str,
) -> None:
    now = datetime.now(tz=UTC)
    session_ids = select(MobileDeviceSessionModel.id).where(
        MobileDeviceSessionModel.agency_id == agency_id,
        MobileDeviceSessionModel.user_id == user_id,
        MobileDeviceSessionModel.status == "active",
    )
    await session.execute(
        update(MobileRefreshTokenModel)
        .where(
            MobileRefreshTokenModel.agency_id == agency_id,
            MobileRefreshTokenModel.session_id.in_(session_ids),
            MobileRefreshTokenModel.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoke_reason=reason)
    )
    await session.execute(
        update(MobileDeviceSessionModel)
        .where(
            MobileDeviceSessionModel.agency_id == agency_id,
            MobileDeviceSessionModel.user_id == user_id,
            MobileDeviceSessionModel.status == "active",
        )
        .values(
            status="revoked",
            session_generation=MobileDeviceSessionModel.session_generation + 1,
            revoked_at=now,
            revoke_reason=reason,
            updated_at=now,
        )
    )


async def _revoke_group_mobile_sessions(
    session: AsyncSession,
    access: GCGroupAccessModel,
    *,
    subject_roles: set[str],
    reason: str,
) -> None:
    """Fence sessions affected by a group-level role or time-window revocation."""

    role_filters = []
    if "passenger" in subject_roles:
        passenger_identity_ids = select(MobilePassengerIdentityModel.id).where(
            MobilePassengerIdentityModel.agency_id == access.agency_id,
            MobilePassengerIdentityModel.gc_group_access_id == access.id,
            MobilePassengerIdentityModel.group_id == access.group_id,
        )
        role_filters.append(
            and_(
                MobileDeviceSessionModel.subject_role == "passenger",
                MobileDeviceSessionModel.passenger_identity_id.in_(
                    passenger_identity_ids
                ),
            )
        )
    if "client_manager" in subject_roles:
        manager_user_ids = (
            select(ClientManagerProfileModel.user_id)
            .join(
                ClientManagerGroupAssignmentModel,
                ClientManagerGroupAssignmentModel.profile_id
                == ClientManagerProfileModel.id,
            )
            .where(
                ClientManagerProfileModel.agency_id == access.agency_id,
                ClientManagerGroupAssignmentModel.agency_id == access.agency_id,
                ClientManagerGroupAssignmentModel.gc_group_access_id == access.id,
                ClientManagerGroupAssignmentModel.group_id == access.group_id,
            )
        )
        role_filters.append(
            and_(
                MobileDeviceSessionModel.subject_role == "client_manager",
                MobileDeviceSessionModel.user_id.in_(manager_user_ids),
            )
        )
    if "coordinator" in subject_roles:
        coordinator_user_ids = select(
            CoordinatorGroupAssignmentModel.coordinator_user_id
        ).where(
            CoordinatorGroupAssignmentModel.agency_id == access.agency_id,
            CoordinatorGroupAssignmentModel.group_id == access.group_id,
        )
        role_filters.append(
            and_(
                MobileDeviceSessionModel.subject_role == "coordinator",
                MobileDeviceSessionModel.user_id.in_(coordinator_user_ids),
            )
        )
    if not role_filters:
        return

    now = datetime.now(tz=UTC)
    affected_session_ids = select(MobileDeviceSessionModel.id).where(
        MobileDeviceSessionModel.agency_id == access.agency_id,
        MobileDeviceSessionModel.status == "active",
        MobileDeviceSessionModel.revoked_at.is_(None),
        or_(
            and_(
                MobileDeviceSessionModel.selected_gc_group_access_id == access.id,
                MobileDeviceSessionModel.subject_role.in_(subject_roles),
            ),
            *role_filters,
        ),
    )
    await session.execute(
        update(MobileRefreshTokenModel)
        .where(
            MobileRefreshTokenModel.agency_id == access.agency_id,
            MobileRefreshTokenModel.session_id.in_(affected_session_ids),
            MobileRefreshTokenModel.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoke_reason=reason)
    )
    await session.execute(
        update(MobileDeviceSessionModel)
        .where(MobileDeviceSessionModel.id.in_(affected_session_ids))
        .values(
            status="revoked",
            session_generation=MobileDeviceSessionModel.session_generation + 1,
            revoked_at=now,
            revoke_reason=reason,
            updated_at=now,
        )
    )


async def _group_access_response(
    session: AsyncSession, access: GCGroupAccessModel
) -> GCGroupAccessResponse:
    # Active counts are scoped to devices that selected this trip; no PII is
    # exposed and accounts with several trips are not double-counted here.
    now = datetime.now(tz=UTC)
    usage = (
        await session.execute(
            select(
                func.count(func.distinct(MobileDeviceSessionModel.account_id)),
                func.count(
                    func.distinct(MobileDeviceSessionModel.device_identifier_hash)
                ).filter(
                    MobileDeviceSessionModel.last_sync_acknowledged_at.is_not(None)
                ),
            ).where(
                MobileDeviceSessionModel.agency_id == access.agency_id,
                MobileDeviceSessionModel.selected_gc_group_access_id == access.id,
                MobileDeviceSessionModel.status == "active",
                MobileDeviceSessionModel.revoked_at.is_(None),
                MobileDeviceSessionModel.expires_at > now,
            )
        )
    ).one()
    active_mobile_users = int(usage[0] or 0)
    synced_device_count = int(usage[1] or 0)
    context = (
        await session.execute(
            select(ClientGroupModel, ClientOrganizationModel)
            .join(
                ClientOrganizationModel,
                (ClientOrganizationModel.id == access.client_organization_id)
                & (ClientOrganizationModel.agency_id == access.agency_id),
            )
            .where(
                ClientGroupModel.id == access.group_id,
                ClientGroupModel.agency_id == access.agency_id,
            )
            .limit(1)
        )
    ).first()
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GC App group context not found",
        )
    group, organization = context
    return GCGroupAccessResponse(
        group_id=access.group_id,
        agency_id=access.agency_id,
        name=group.name,
        destination=group.destination,
        travel_date=group.travel_date,
        return_date=group.return_date,
        lifecycle_status=group.status,
        client_organization_id=organization.id,
        client_organization_name=organization.name,
        enabled=access.is_enabled,
        passenger_access_enabled=access.passenger_access_enabled,
        client_manager_access_enabled=access.client_manager_access_enabled,
        coordinator_access_enabled=access.coordinator_access_enabled,
        access_starts_at=access.access_starts_at,
        access_expires_at=access.access_expires_at,
        revoked_at=access.revoked_at,
        access_generation=access.access_generation,
        itinerary_version=access.itinerary_version,
        common_document_version=access.common_document_version,
        announcement_version=access.announcement_version,
        revision=access.revision,
        last_successful_sync_at=access.last_successful_sync_at,
        active_mobile_users=active_mobile_users,
        synced_device_count=synced_device_count,
        updated_at=access.updated_at,
    )


def _organization_response(item: ClientOrganizationModel) -> ClientOrganizationResponse:
    return ClientOrganizationResponse(
        id=item.id,
        agency_id=item.agency_id,
        name=item.name,
        status=item.status,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _client_manager_response(
    profile: ClientManagerProfileModel,
    user: UserModel,
    organization: ClientOrganizationModel,
    assigned_groups: list[ClientManagerAssignedGroupResponse],
) -> ClientManagerResponse:
    return ClientManagerResponse(
        id=profile.id,
        user_id=user.id,
        agency_id=profile.agency_id,
        full_name=user.full_name,
        email=user.email,
        phone_number=profile.normalized_phone_number,
        organization_id=organization.id,
        organization_name=organization.name,
        status=profile.status,
        force_password_change=profile.force_password_change,
        revision=profile.revision,
        group_ids=[group.id for group in assigned_groups],
        assigned_groups=assigned_groups,
        last_login_at=user.last_login_at,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _require_revision(current: int, expected: int) -> None:
    if current != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client Manager changed; refresh and retry",
        )


async def _audit(
    session: AsyncSession,
    actor: User,
    request: Request,
    *,
    agency_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    metadata: dict[str, object] | None,
) -> None:
    await AuditLogRepository(session).record(
        action=action,
        entity_type=entity_type,
        agency_id=agency_id,
        user_id=actor.id,
        actor_email=actor.email,
        entity_id=str(entity_id),
        ip_address=trusted_client_ip(request),
        metadata=metadata,
    )
