"""Project group directory query rows using canonical availability fields."""

from __future__ import annotations

from datetime import datetime

from app.application.mobile.group_app_availability import availability_fields
from app.presentation.api.v1.routes.gc_group_directory_query import GCGroupDirectoryRow
from app.presentation.api.v1.schemas.gc_app_schemas import GCGroupSearchAccess, GCGroupSearchItem


def project_gc_group_directory(
    rows: list[GCGroupDirectoryRow], *, now: datetime
) -> list[GCGroupSearchItem]:
    items: list[GCGroupSearchItem] = []
    for group, access, organization, active_mobile_users, synced_device_count in rows:
        items.append(
            GCGroupSearchItem(
                **availability_fields(group, access, now=now),
                id=group.id,
                agency_id=group.agency_id,
                name=group.name,
                destination=group.destination,
                travel_date=group.travel_date,
                return_date=group.return_date,
                lifecycle_status=group.status,
                gc_enabled=bool(access and access.is_enabled and access.revoked_at is None),
                client_organization_id=(group.company_id),
                client_organization_name=(organization.name if organization else None),
                access=(
                    GCGroupSearchAccess(
                        **availability_fields(group, access, now=now),
                        group_id=group.id,
                        agency_id=group.agency_id,
                        client_organization_id=access.client_organization_id,
                        client_organization_name=organization.name if organization else None,
                        enabled=access.is_enabled,
                        passenger_access_enabled=access.passenger_access_enabled,
                        client_manager_access_enabled=access.client_manager_access_enabled,
                        coordinator_access_enabled=access.coordinator_access_enabled,
                        access_starts_at=access.access_starts_at,
                        access_expires_at=access.access_expires_at,
                        revoked_at=access.revoked_at,
                        removed_at=access.removed_at,
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
                    if access is not None
                    else None
                ),
            )
        )
    return items
