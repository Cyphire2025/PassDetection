"""Monotonic delivery outcomes and parent state projection."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.fcm_dispatch_intents import UNKNOWN_CODE
from app.application.mobile.mcp_push_guard import observe_push
from app.infrastructure.database.gc_mobile_models import (
    MobileNotificationModel,
    MobilePushDeliveryModel,
    MobilePushRegistrationModel,
)


def _retry_delivery(
    delivery: MobilePushDeliveryModel,
    now: datetime,
    code: str,
    *,
    delay_seconds: int,
) -> None:
    if delivery.status in {"delivered", "failed", "cancelled", "provider_accepted", "unknown"}:
        return
    delivery.status = "retry"
    delivery.provider_ticket_id = None
    delivery.submitted_at = None
    delivery.delivered_at = None
    delivery.failed_at = None
    delivery.next_attempt_at = now + timedelta(seconds=delay_seconds)
    delivery.last_error_code = code
    delivery.updated_at = now


def _fail_delivery(
    delivery: MobilePushDeliveryModel,
    now: datetime,
    code: str,
) -> None:
    if delivery.status in {"delivered", "cancelled", "provider_accepted", "unknown"}:
        return
    delivery.status = "failed"
    delivery.delivered_at = None
    delivery.failed_at = delivery.failed_at or now
    delivery.last_error_code = code
    delivery.updated_at = now


def _revoke_registration(
    registration: MobilePushRegistrationModel,
    now: datetime,
    code: str,
) -> None:
    if registration.status != "revoked":
        registration.status = "revoked"
        registration.notifications_authorized = False
        registration.revoked_at = now
    registration.last_failure_at = now
    registration.last_failure_code = code
    registration.updated_at = now


async def _refresh_notification_delivery_states(
    session: AsyncSession,
    *,
    notifications: list[MobileNotificationModel],
    now: datetime,
) -> None:
    if not notifications:
        return
    notification_ids = [item.id for item in notifications]
    deliveries = list(
        (
            await session.execute(
                select(MobilePushDeliveryModel).where(
                    MobilePushDeliveryModel.notification_id.in_(notification_ids)
                )
            )
        ).scalars()
    )
    grouped: dict[uuid.UUID, list[MobilePushDeliveryModel]] = {}
    for delivery in deliveries:
        grouped.setdefault(delivery.notification_id, []).append(delivery)

    for notification in notifications:
        if notification.status == "cancelled":
            continue
        rows = grouped.get(notification.id, [])
        if not rows:
            continue
        if any(item.status in {"delivered", "provider_accepted"} for item in rows):
            notification.status = "sent"
            notification.sent_at = notification.sent_at or now
            notification.failure_code = None
            notification.updated_at = now
            continue
        if notification.status == "sent":
            continue
        pending = [
            item for item in rows if item.status in {"submitting", "retry", "receipt_pending"}
        ]
        if pending:
            notification.status = "queued"
            retry_errors = [
                item.last_error_code
                for item in pending
                if item.status == "retry" and item.last_error_code is not None
            ]
            notification.failure_code = retry_errors[0] if retry_errors else None
            notification.updated_at = now
            continue
        notification.status = "failed"
        notification.failure_code = (
            UNKNOWN_CODE
            if any(item.status == "unknown" for item in rows)
            else next(
                (item.last_error_code for item in rows if item.last_error_code is not None),
                "provider_rejected",
            )
        )
        notification.updated_at = now
    await observe_push(session, notifications)


def _bounded_backoff_seconds(
    base_seconds: int,
    attempt: int,
    *,
    maximum: int = 900,
) -> int:
    exponent = max(0, min(attempt - 1, 10))
    return min(maximum, int(base_seconds * (2**exponent)))


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
