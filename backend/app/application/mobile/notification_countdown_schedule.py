"""Reconcile countdown schedules against current trip windows."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.notification_contracts import (
    _COUNTDOWN_CLEANUP_PAGE_SIZE,
    _COUNTDOWN_DAYS,
    _COUNTDOWN_NOTIFICATION_TYPE,
    CountdownNotificationCounts,
)
from app.application.mobile.notification_countdown_recipients import _enqueue_countdown_recipients
from app.application.mobile.notification_delivery_states import _aware_utc
from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE, normalize_trip_timezone
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobileNotificationModel,
    MobilePushDeliveryModel,
)
from app.infrastructure.database.models import ClientGroupModel


async def schedule_trip_countdown_notifications(
    session: AsyncSession,
    *,
    timezone_name: str,
    send_hour: int = 9,
    now: datetime | None = None,
) -> CountdownNotificationCounts:
    """Reconcile future 3/2/1-day push-only trip countdowns.

    The trip model stores an authoritative date and IANA timezone rather than a
    departure timestamp. The group timezone and configured local send hour
    therefore define each delivery instant. ``timezone_name`` remains the
    rolling-deployment fallback for rows/test doubles that predate the column.
    Passed instants are never caught up, preventing newly enabled groups from
    receiving a burst of stale countdowns.
    """

    if send_hour < 0 or send_hour > 23:
        raise ValueError("Countdown send hour must be between 0 and 23")
    fallback_timezone_name = normalize_trip_timezone(timezone_name)
    current = _aware_utc(now or datetime.now(tz=UTC))
    assert current is not None
    # The indexed coarse window spans the maximum one-day civil offset
    # difference. Exact eligibility is checked in each trip timezone below.
    first_candidate_date = current.date()
    last_candidate_date = current.date() + timedelta(days=367)

    cancelled = await _cancel_stale_countdowns(session, now=current)
    inserted = 0
    groups_scanned = 0
    cursor: uuid.UUID | None = None
    while True:
        statement = (
            select(GCGroupAccessModel, ClientGroupModel)
            .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
            .where(
                ClientGroupModel.agency_id == GCGroupAccessModel.agency_id,
                ClientGroupModel.status.in_(("active", "closed")),
                ClientGroupModel.travel_date >= first_candidate_date,
                ClientGroupModel.travel_date <= last_candidate_date,
                GCGroupAccessModel.is_enabled.is_(True),
                GCGroupAccessModel.revoked_at.is_(None),
                or_(
                    GCGroupAccessModel.passenger_access_enabled.is_(True),
                    GCGroupAccessModel.client_manager_access_enabled.is_(True),
                    GCGroupAccessModel.coordinator_access_enabled.is_(True),
                ),
            )
            .order_by(GCGroupAccessModel.id.asc())
            .limit(100)
        )
        if cursor is not None:
            statement = statement.where(GCGroupAccessModel.id > cursor)
        rows = list((await session.execute(statement)).all())
        if not rows:
            break
        for access, group in rows:
            groups_scanned += 1
            if group.travel_date is None:
                continue
            trip_timezone_name = normalize_trip_timezone(
                getattr(group, "timezone", None) or fallback_timezone_name
            )
            trip_timezone = ZoneInfo(trip_timezone_name)
            local_today = current.astimezone(trip_timezone).date()
            if not (local_today < group.travel_date <= local_today + timedelta(days=366)):
                continue
            trip_starts_at = datetime.combine(
                group.travel_date,
                time.min,
                tzinfo=trip_timezone,
            ).astimezone(UTC)
            access_start = _aware_utc(access.access_starts_at)
            access_expiry = _aware_utc(access.access_expires_at)
            for days_remaining in _COUNTDOWN_DAYS:
                scheduled_at = datetime.combine(
                    group.travel_date - timedelta(days=days_remaining),
                    time(hour=send_hour),
                    tzinfo=trip_timezone,
                ).astimezone(UTC)
                if scheduled_at <= current:
                    continue
                if access_start is not None and access_start > scheduled_at:
                    continue
                expires_at = min(
                    value for value in (access_expiry, trip_starts_at) if value is not None
                )
                if expires_at <= scheduled_at:
                    continue
                inserted += await _enqueue_countdown_recipients(
                    session,
                    access=access,
                    travel_date=group.travel_date,
                    timezone_name=trip_timezone_name,
                    days_remaining=days_remaining,
                    available_at=scheduled_at,
                    expires_at=expires_at,
                )
        cursor = rows[-1][0].id
        if len(rows) < 100:
            break
    return CountdownNotificationCounts(
        inserted=inserted,
        cancelled=cancelled,
        groups_scanned=groups_scanned,
    )


async def _cancel_stale_countdowns(
    session: AsyncSession,
    *,
    now: datetime,
) -> int:
    cancelled = 0
    cursor: uuid.UUID | None = None
    while True:
        statement = (
            select(
                MobileNotificationModel,
                GCGroupAccessModel,
                ClientGroupModel,
            )
            .join(
                GCGroupAccessModel,
                GCGroupAccessModel.id == MobileNotificationModel.gc_group_access_id,
            )
            .join(
                ClientGroupModel,
                ClientGroupModel.id == MobileNotificationModel.group_id,
            )
            .where(
                MobileNotificationModel.notification_type == _COUNTDOWN_NOTIFICATION_TYPE,
                MobileNotificationModel.status == "queued",
            )
            .order_by(MobileNotificationModel.id.asc())
            .limit(_COUNTDOWN_CLEANUP_PAGE_SIZE)
        )
        if cursor is not None:
            statement = statement.where(MobileNotificationModel.id > cursor)
        rows = list((await session.execute(statement)).all())
        if not rows:
            break
        cancelled_ids: list[uuid.UUID] = []
        for notification, access, group in rows:
            role_enabled = {
                "passenger": access.passenger_access_enabled,
                "client_manager": access.client_manager_access_enabled,
                "coordinator": access.coordinator_access_enabled,
            }.get(notification.recipient_type, False)
            scheduled_at = _aware_utc(notification.available_at)
            expires_at = _aware_utc(notification.expires_at)
            access_start = _aware_utc(access.access_starts_at)
            access_expiry = _aware_utc(access.access_expires_at)
            trip_timezone_name = normalize_trip_timezone(
                getattr(group, "timezone", None) or DEFAULT_TRIP_TIMEZONE
            )
            current_schedule = group.travel_date is not None and notification.dedupe_key.startswith(
                f"trip-countdown:{group.travel_date.isoformat()}:{trip_timezone_name}:"
            )
            invalid = (
                group.status not in {"active", "closed"}
                or not access.is_enabled
                or access.revoked_at is not None
                or not role_enabled
                or not current_schedule
                or scheduled_at is None
                or (access_start is not None and access_start > scheduled_at)
                or (access_expiry is not None and access_expiry <= scheduled_at)
                or (expires_at is not None and expires_at <= now)
            )
            if not invalid:
                continue
            notification.status = "cancelled"
            notification.failure_code = "countdown_schedule_changed"
            notification.updated_at = now
            cancelled_ids.append(notification.id)
        if cancelled_ids:
            await session.execute(
                update(MobilePushDeliveryModel)
                .where(
                    MobilePushDeliveryModel.notification_id.in_(cancelled_ids),
                    MobilePushDeliveryModel.status.in_(("submitting", "retry")),
                )
                .values(
                    status="cancelled",
                    last_error_code="countdown_schedule_changed",
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            cancelled += len(cancelled_ids)
        cursor = rows[-1][0].id
        if len(rows) < _COUNTDOWN_CLEANUP_PAGE_SIZE:
            break
    return cancelled
