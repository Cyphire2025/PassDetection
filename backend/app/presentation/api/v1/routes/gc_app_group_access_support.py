"""Focused group-access projections and passenger feature mutations."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import GroupStatus, User
from app.infrastructure.database.gc_mobile_models import (
    ClientOrganizationModel,
    GCGroupAccessModel,
    MobileDeviceSessionModel,
)
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.my_photos_models import MyPhotoGalleryModel
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCGroupAccessResponse,
    GCMyPhotosFeatureUpdateRequest,
)

MobileSyncAppender = Callable[..., Awaitable[object]]
AuditRecorder = Callable[..., Awaitable[None]]
GroupAccessResponseBuilder = Callable[..., Awaitable[GCGroupAccessResponse]]


async def configure_my_photos_feature(
    *,
    session: AsyncSession,
    group: ClientGroupModel,
    access: GCGroupAccessModel,
    body: GCMyPhotosFeatureUpdateRequest,
    request: Request,
    current_user_id: uuid.UUID,
    current_user: User,
    tenant_id: uuid.UUID,
    append_change: MobileSyncAppender,
    audit_change: AuditRecorder,
    response_builder: GroupAccessResponseBuilder,
) -> GCGroupAccessResponse:
    """Toggle My Photos while retaining the caller's group/access lock order."""

    if body.expected_revision != access.revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="GC App settings changed; refresh and retry",
        )
    if body.enabled and (
        group.status not in {GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value}
        or not access.is_enabled
        or not access.passenger_access_enabled
        or access.revoked_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Enable GC App passenger access before enabling My Photos",
        )

    gallery = (
        await session.execute(
            select(MyPhotoGalleryModel)
            .where(
                MyPhotoGalleryModel.agency_id == tenant_id,
                MyPhotoGalleryModel.group_id == access.group_id,
                MyPhotoGalleryModel.gc_group_access_id == access.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    currently_enabled = bool(gallery is not None and gallery.feature_enabled)
    if currently_enabled == body.enabled:
        return await response_builder(session, access)

    now = datetime.now(tz=UTC)
    if gallery is None:
        # The gallery row is the durable feature boundary. Creating an inert
        # placeholder keeps the future upload/index workflow additive.
        gallery = MyPhotoGalleryModel(
            id=uuid.uuid4(),
            agency_id=tenant_id,
            group_id=access.group_id,
            gc_group_access_id=access.id,
            feature_enabled=True,
            status="not_uploaded",
            created_at=now,
            updated_at=now,
        )
        session.add(gallery)
    else:
        gallery.feature_enabled = body.enabled
        gallery.updated_at = now

    # Capability visibility is a lightweight manifest change. It must not
    # rotate access_generation or revoke otherwise-valid mobile sessions.
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user_id
    access.updated_at = now
    await session.flush()
    await append_change(
        session,
        access=access,
        audience="passenger",
        entity_type="my_photos_capability",
        entity_id=gallery.id,
        operation="upsert",
        version=access.manifest_version,
        changed_by_user_id=current_user_id,
        payload={
            "resource_path": f"/api/v1/mobile/trips/{access.group_id}/my-photos",
        },
    )
    await audit_change(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action=("gc_app.my_photos_enabled" if body.enabled else "gc_app.my_photos_disabled"),
        entity_type="my_photos_gallery",
        entity_id=gallery.id,
        metadata={"group_id": str(access.group_id), "enabled": body.enabled},
    )
    return await response_builder(session, access)


async def group_access_response(
    session: AsyncSession, access: GCGroupAccessModel
) -> GCGroupAccessResponse:
    """Build the canonical access response, including My Photos visibility."""

    # Active counts are scoped to devices that selected this trip; no PII is
    # exposed and accounts with several trips are not double-counted here.
    now = datetime.now(tz=UTC)
    usage = (
        await session.execute(
            select(
                func.count(func.distinct(MobileDeviceSessionModel.account_id)),
                func.count(func.distinct(MobileDeviceSessionModel.device_identifier_hash)).filter(
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
            select(
                ClientGroupModel,
                ClientOrganizationModel,
                MyPhotoGalleryModel.feature_enabled,
            )
            .join(
                ClientOrganizationModel,
                (ClientOrganizationModel.id == access.client_organization_id)
                & (ClientOrganizationModel.agency_id == access.agency_id),
            )
            .outerjoin(
                MyPhotoGalleryModel,
                (MyPhotoGalleryModel.gc_group_access_id == access.id)
                & (MyPhotoGalleryModel.agency_id == access.agency_id)
                & (MyPhotoGalleryModel.group_id == access.group_id),
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
    group, organization, my_photos_enabled = context
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
        my_photos_enabled=bool(my_photos_enabled),
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
