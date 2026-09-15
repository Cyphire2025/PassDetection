"""Revalidate queued announcement sources in the outbound push transaction."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
    MobileNotificationModel,
    MobilePushDeliveryModel,
)

_SourceScope = tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]
_ROLE_VISIBILITY = {
    "passenger": "passenger_visible",
    "client_manager": "client_manager_visible",
    "coordinator": "coordinator_visible",
}


async def retain_dispatchable_announcement_notifications(
    session: AsyncSession,
    *,
    notifications: list[MobileNotificationModel],
    now: datetime,
) -> list[MobileNotificationModel]:
    """Cancel obsolete sources and defer locked ones; preserve other push types.

    The dispatcher already owns notification row locks. Content withdrawal owns
    the announcement first and then cancels its notifications, so waiting here
    for a source lock would invert that order and deadlock. Shared, nonwaiting
    locks fence a validated source until the caller commits the send transaction.
    A withdrawal that acquired its lock first wins; that source is deferred.
    """
    candidates: dict[uuid.UUID, _SourceScope] = {}
    cancelled: list[MobileNotificationModel] = []
    retained: list[MobileNotificationModel] = []
    for notification in notifications:
        if notification.notification_type != "group_announcement":
            retained.append(notification)
            continue
        scope = _source_scope(notification)
        if scope is None:
            _cancel(notification, "invalid_public_payload", now)
            cancelled.append(notification)
        else:
            candidates[notification.id] = scope

    if candidates:
        scope_columns = tuple_(
            GCAnnouncementModel.id,
            GCAnnouncementModel.agency_id,
            GCAnnouncementModel.group_id,
            GCAnnouncementModel.gc_group_access_id,
        )
        scopes = set(candidates.values())
        sources = list(
            (
                await session.execute(
                    select(GCAnnouncementModel)
                    .where(scope_columns.in_(scopes))
                    .order_by(GCAnnouncementModel.id)
                    .with_for_update(read=True, skip_locked=True)
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        )
        source_by_scope = {
            (source.id, source.agency_id, source.group_id, source.gc_group_access_id): source
            for source in sources
        }
        omitted_scopes = scopes - source_by_scope.keys()
        # SKIP LOCKED also omits live rows currently being edited. A plain MVCC
        # read distinguishes them from truly missing/deleted or mismatched rows.
        existing_omitted: set[_SourceScope] = set()
        if omitted_scopes:
            existing_omitted = {
                (row.id, row.agency_id, row.group_id, row.gc_group_access_id)
                for row in (
                    await session.execute(
                        select(
                            GCAnnouncementModel.id,
                            GCAnnouncementModel.agency_id,
                            GCAnnouncementModel.group_id,
                            GCAnnouncementModel.gc_group_access_id,
                        ).where(scope_columns.in_(omitted_scopes))
                    )
                )
            }
        for notification in notifications:
            scope = candidates.get(notification.id)
            if scope is None or scope in existing_omitted:
                continue
            source = source_by_scope.get(scope)
            if source is None or not _is_visible_published_source(source, notification, now):
                _cancel(notification, "announcement_unpublished", now)
                cancelled.append(notification)
                continue
            starts_at = _aware_utc(source.availability_starts_at)
            if starts_at is not None and starts_at > now:
                notification_expiry = _aware_utc(notification.expires_at)
                if notification_expiry is not None and notification_expiry <= starts_at:
                    _cancel(notification, "announcement_unpublished", now)
                    cancelled.append(notification)
                else:
                    notification.available_at = starts_at
                    notification.updated_at = now
                continue
            retained.append(notification)

    if cancelled:
        # Do not erase accepted provider tickets or delivery/receipt evidence.
        for failure_code in {item.failure_code for item in cancelled}:
            await session.execute(
                update(MobilePushDeliveryModel)
                .where(
                    tuple_(
                        MobilePushDeliveryModel.notification_id,
                        MobilePushDeliveryModel.agency_id,
                    ).in_(
                        [
                            (item.id, item.agency_id)
                            for item in cancelled
                            if item.failure_code == failure_code
                        ]
                    ),
                    MobilePushDeliveryModel.status.in_(["submitting", "retry"]),
                )
                .values(status="cancelled", last_error_code=failure_code, updated_at=now)
                .execution_options(synchronize_session="fetch")
            )
        await session.flush()
    retained_ids = {item.id for item in retained}
    return [item for item in notifications if item.id in retained_ids]


def _source_scope(notification: MobileNotificationModel) -> _SourceScope | None:
    payload = notification.public_payload
    event_id = payload.get("event_id") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("route") != "updates"
        or payload.get("trip_id") != str(notification.group_id)
        or not isinstance(event_id, str)
        or notification.group_id is None
        or notification.gc_group_access_id is None
    ):
        return None
    try:
        source_id = uuid.UUID(event_id)
    except ValueError:
        return None
    if notification.dedupe_key != f"announcement:{source_id}":
        return None
    return (
        source_id,
        notification.agency_id,
        notification.group_id,
        notification.gc_group_access_id,
    )


def _is_visible_published_source(
    source: GCAnnouncementModel,
    notification: MobileNotificationModel,
    now: datetime,
) -> bool:
    visibility_field = _ROLE_VISIBILITY.get(notification.recipient_type)
    expires_at = _aware_utc(source.availability_expires_at)
    return (
        source.status == "published"
        and source.retired_at is None
        and source.revoked_at is None
        and visibility_field is not None
        and bool(getattr(source, visibility_field, False))
        and (expires_at is None or expires_at > now)
    )


def _cancel(notification: MobileNotificationModel, failure_code: str, now: datetime) -> None:
    notification.status = "cancelled"
    notification.failure_code = failure_code
    notification.updated_at = now


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
