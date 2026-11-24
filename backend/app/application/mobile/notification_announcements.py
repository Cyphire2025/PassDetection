"""Tenant-scoped announcement feed production and withdrawal."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.application.mobile.notification_contracts import (
    _LOCK_SCREEN_TITLE,
    _NOTIFICATION_TYPE,
    _RECIPIENT_PAGE_SIZE,
    AnnouncementNotificationCounts,
)
from app.application.mobile.passenger_notification_authority import retain_recipient_ids
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    GCAnnouncementModel,
    GCGroupAccessModel,
    MobileNotificationModel,
    MobilePassengerIdentityModel,
    MobilePushDeliveryModel,
)
from app.infrastructure.database.models import CoordinatorGroupAssignmentModel, UserModel


async def enqueue_announcement_notifications(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    announcement: GCAnnouncementModel,
    now: datetime | None = None,
) -> AnnouncementNotificationCounts:
    """Create one deduplicated feed row per currently authorized principal."""

    current = now or datetime.now(tz=UTC)
    if not access.is_enabled or access.revoked_at is not None:
        return AnnouncementNotificationCounts()
    available_at = max(
        value
        for value in (current, access.access_starts_at, announcement.availability_starts_at)
        if value is not None
    )
    expiry_candidates = [
        value
        for value in (access.access_expires_at, announcement.availability_expires_at)
        if value is not None
    ]
    expires_at = min(expiry_candidates) if expiry_candidates else None
    if expires_at is not None and expires_at <= available_at:
        return AnnouncementNotificationCounts()

    passengers = 0
    managers = 0
    coordinators = 0
    if access.passenger_access_enabled and announcement.passenger_visible:
        passengers = await _enqueue_recipient_pages(
            session,
            statement=select(MobilePassengerIdentityModel.id).where(
                MobilePassengerIdentityModel.agency_id == access.agency_id,
                MobilePassengerIdentityModel.gc_group_access_id == access.id,
                MobilePassengerIdentityModel.group_id == access.group_id,
                MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
            ),
            id_column=MobilePassengerIdentityModel.id,
            recipient_type="passenger",
            access=access,
            announcement=announcement,
            available_at=available_at,
            expires_at=expires_at,
        )
    if access.client_manager_access_enabled and announcement.client_manager_visible:
        managers = await _enqueue_recipient_pages(
            session,
            statement=(
                select(UserModel.id)
                .join(
                    ClientManagerProfileModel,
                    ClientManagerProfileModel.user_id == UserModel.id,
                )
                .join(
                    ClientManagerGroupAssignmentModel,
                    ClientManagerGroupAssignmentModel.profile_id == ClientManagerProfileModel.id,
                )
                .where(
                    UserModel.agency_id == access.agency_id,
                    UserModel.role == "client_manager",
                    UserModel.is_active.is_(True),
                    UserModel.deleted_at.is_(None),
                    ClientManagerProfileModel.agency_id == access.agency_id,
                    ClientManagerProfileModel.status == "active",
                    ClientManagerProfileModel.deleted_at.is_(None),
                    ClientManagerGroupAssignmentModel.agency_id == access.agency_id,
                    ClientManagerGroupAssignmentModel.gc_group_access_id == access.id,
                    ClientManagerGroupAssignmentModel.group_id == access.group_id,
                    ClientManagerGroupAssignmentModel.is_active.is_(True),
                    ClientManagerGroupAssignmentModel.revoked_at.is_(None),
                )
            ),
            id_column=UserModel.id,
            recipient_type="client_manager",
            access=access,
            announcement=announcement,
            available_at=available_at,
            expires_at=expires_at,
        )
    if access.coordinator_access_enabled and announcement.coordinator_visible:
        coordinators = await _enqueue_recipient_pages(
            session,
            statement=(
                select(UserModel.id)
                .join(
                    CoordinatorGroupAssignmentModel,
                    CoordinatorGroupAssignmentModel.coordinator_user_id == UserModel.id,
                )
                .where(
                    UserModel.agency_id == access.agency_id,
                    UserModel.role == "agency_coordinator",
                    UserModel.is_active.is_(True),
                    UserModel.deleted_at.is_(None),
                    CoordinatorGroupAssignmentModel.agency_id == access.agency_id,
                    CoordinatorGroupAssignmentModel.group_id == access.group_id,
                    CoordinatorGroupAssignmentModel.active.is_(True),
                )
            ),
            id_column=UserModel.id,
            recipient_type="coordinator",
            access=access,
            announcement=announcement,
            available_at=available_at,
            expires_at=expires_at,
        )
    return AnnouncementNotificationCounts(
        passengers=passengers,
        client_managers=managers,
        coordinators=coordinators,
    )


async def cancel_announcement_notifications(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    announcement_id: uuid.UUID,
    now: datetime | None = None,
) -> int:
    """Remove a revoked announcement from the in-app feed and stop unsent pushes."""

    result = await session.execute(
        update(MobileNotificationModel)
        .where(
            MobileNotificationModel.agency_id == access.agency_id,
            MobileNotificationModel.gc_group_access_id == access.id,
            MobileNotificationModel.dedupe_key == _announcement_dedupe_key(announcement_id),
            MobileNotificationModel.status.in_(("queued", "sent", "failed")),
        )
        .values(
            status="cancelled",
            failure_code="announcement_unpublished",
            updated_at=now or datetime.now(tz=UTC),
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(MobilePushDeliveryModel)
        .where(
            MobilePushDeliveryModel.notification_id.in_(
                select(MobileNotificationModel.id).where(
                    MobileNotificationModel.agency_id == access.agency_id,
                    MobileNotificationModel.gc_group_access_id == access.id,
                    MobileNotificationModel.dedupe_key == _announcement_dedupe_key(announcement_id),
                    MobileNotificationModel.status == "cancelled",
                )
            ),
            MobilePushDeliveryModel.status.in_(("submitting", "retry")),
        )
        .values(
            status="cancelled",
            last_error_code="announcement_unpublished",
            updated_at=now or datetime.now(tz=UTC),
        )
        .execution_options(synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def _enqueue_recipient_pages(
    session: AsyncSession,
    *,
    statement: Select[tuple[uuid.UUID]],
    id_column: InstrumentedAttribute[uuid.UUID],
    recipient_type: str,
    access: GCGroupAccessModel,
    announcement: GCAnnouncementModel,
    available_at: datetime,
    expires_at: datetime | None,
) -> int:
    cursor: uuid.UUID | None = None
    inserted = 0
    while True:
        page_statement = statement
        if cursor is not None:
            page_statement = page_statement.where(id_column > cursor)
        ids = list(
            (
                await session.execute(
                    page_statement.order_by(id_column.asc()).limit(_RECIPIENT_PAGE_SIZE)
                )
            ).scalars()
        )
        if not ids:
            break
        allowed_ids = await retain_recipient_ids(
            session, recipient_ids=ids, recipient_type=recipient_type, access=access
        )
        for recipient_id in allowed_ids:
            session.add(
                _announcement_notification(
                    recipient_id=recipient_id,
                    recipient_type=recipient_type,
                    access=access,
                    announcement=announcement,
                    available_at=available_at,
                    expires_at=expires_at,
                )
            )
        await session.flush()
        inserted += len(allowed_ids)
        cursor = ids[-1]
        if len(ids) < _RECIPIENT_PAGE_SIZE:
            break
    return inserted


def _announcement_notification(
    *,
    recipient_id: uuid.UUID,
    recipient_type: str,
    access: GCGroupAccessModel,
    announcement: GCAnnouncementModel,
    available_at: datetime,
    expires_at: datetime | None,
) -> MobileNotificationModel:
    is_passenger = recipient_type == "passenger"
    return MobileNotificationModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        recipient_type=recipient_type,
        recipient_user_id=None if is_passenger else recipient_id,
        recipient_passenger_identity_id=recipient_id if is_passenger else None,
        notification_type=_NOTIFICATION_TYPE,
        category=("announcement" if announcement.category == "general" else announcement.category),
        priority=announcement.priority,
        title=announcement.title,
        body=announcement.body,
        lock_screen_title=_LOCK_SCREEN_TITLE,
        lock_screen_body=None,
        contains_sensitive_content=True,
        deep_link_path=(f"/updates?trip_id={access.group_id}&event_id={announcement.id}"),
        dedupe_key=_announcement_dedupe_key(announcement.id),
        public_payload={
            "route": "updates",
            "trip_id": str(access.group_id),
            "event_id": str(announcement.id),
        },
        status="queued",
        available_at=available_at,
        expires_at=expires_at,
    )


def _announcement_dedupe_key(announcement_id: uuid.UUID) -> str:
    return f"announcement:{announcement_id}"
