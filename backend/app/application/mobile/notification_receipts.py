"""Bounded provider receipt reconciliation under parent-first claims."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.notification_delivery_states import (
    _aware_utc,
    _bounded_backoff_seconds,
    _fail_delivery,
    _refresh_notification_delivery_states,
    _revoke_registration,
)
from app.application.mobile.push_provider import MobilePushProvider
from app.application.mobile.push_receipt_claims import claim_mobile_push_receipts
from app.infrastructure.database.gc_mobile_models import (
    MobilePushDeliveryModel,
    MobilePushRegistrationModel,
)
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)


async def reconcile_mobile_push_receipts(
    session: AsyncSession,
    *,
    provider: MobilePushProvider,
    limit: int,
    now: datetime | None = None,
    max_attempts: int = 8,
    max_age: timedelta = timedelta(hours=23),
    retry_base_seconds: int = 60,
) -> int:
    """Poll due provider receipts and apply monotonic delivery transitions."""

    if not provider.enabled or not getattr(provider, "supports_receipts", True):
        return 0
    if limit < 1 or limit > 1_000:
        raise ValueError("Mobile push receipt batch limit must be between 1 and 1,000")
    if max_attempts < 1 or max_age <= timedelta(0) or retry_base_seconds < 1:
        raise ValueError("Mobile push receipt retry policy was invalid")
    current = now or datetime.now(tz=UTC)
    deliveries, notifications = await claim_mobile_push_receipts(
        session,
        provider_name=provider.name,
        limit=limit,
        now=current,
    )
    if not deliveries:
        return 0

    registration_ids = {item.registration_id for item in deliveries}
    registrations = {
        item.id: item
        for item in (
            (
                await session.execute(
                    select(MobilePushRegistrationModel).where(
                        MobilePushRegistrationModel.id.in_(registration_ids)
                    )
                )
            ).scalars()
        )
    }

    eligible: list[MobilePushDeliveryModel] = []
    for delivery in deliveries:
        notification = notifications.get(delivery.notification_id)
        registration = registrations.get(delivery.registration_id)
        if (
            notification is None
            or registration is None
            or notification.agency_id != delivery.agency_id
            or registration.agency_id != delivery.agency_id
        ):
            _fail_delivery(delivery, current, "tenant_scope_mismatch")
            continue
        submitted_at = _aware_utc(delivery.submitted_at)
        if submitted_at is None or current - submitted_at >= max_age:
            _fail_delivery(delivery, current, "receipt_expired")
            registration.last_failure_at = current
            registration.last_failure_code = "receipt_expired"
            registration.updated_at = current
            record_operational_event(OperationalEvent.MOBILE_PUSH, "receipt_failed")
            continue
        eligible.append(delivery)

    if not eligible:
        await session.flush()
        await _refresh_notification_delivery_states(
            session,
            notifications=list(notifications.values()),
            now=current,
        )
        return 0

    ticket_ids = [
        item.provider_ticket_id for item in eligible if item.provider_ticket_id is not None
    ]
    receipt_by_ticket = {
        item.provider_ticket_id: item for item in await provider.get_receipts(ticket_ids)
    }
    delivered_notifications: set[uuid.UUID] = set()
    for delivery in eligible:
        ticket_id = delivery.provider_ticket_id
        if ticket_id is None:
            _fail_delivery(delivery, current, "provider_ticket_missing")
            continue
        registration = registrations[delivery.registration_id]
        receipt = receipt_by_ticket.get(ticket_id)
        delivery.receipt_attempts += 1
        if receipt is not None and receipt.delivered:
            delivery.status = "delivered"
            delivery.delivered_at = current
            delivery.failed_at = None
            delivery.last_error_code = None
            delivery.updated_at = current
            registration.last_success_at = current
            registration.last_failure_code = None
            registration.updated_at = current
            delivered_notifications.add(delivery.notification_id)
            record_operational_event(OperationalEvent.MOBILE_PUSH, "receipt_delivered")
            continue

        code = (
            receipt.error_code
            if receipt is not None and receipt.error_code is not None
            else "provider_missing_receipt_response"
        )
        registration.last_failure_at = current
        registration.last_failure_code = code
        registration.updated_at = current
        if code == "DeviceNotRegistered":
            _revoke_registration(registration, current, code)
            _fail_delivery(delivery, current, code)
            record_operational_event(OperationalEvent.MOBILE_PUSH, "device_revoked")
            continue
        retryable = receipt is None or receipt.retryable
        if retryable and delivery.receipt_attempts < max_attempts:
            delivery.next_attempt_at = current + timedelta(
                seconds=_bounded_backoff_seconds(
                    retry_base_seconds,
                    delivery.receipt_attempts,
                    maximum=3_600,
                )
            )
            delivery.last_error_code = code
            delivery.updated_at = current
            record_operational_event(
                OperationalEvent.MOBILE_PUSH,
                "receipt_retry_scheduled",
            )
        else:
            _fail_delivery(delivery, current, code)
            record_operational_event(OperationalEvent.MOBILE_PUSH, "receipt_failed")

    await session.flush()
    await _refresh_notification_delivery_states(
        session,
        notifications=list(notifications.values()),
        now=current,
    )
    return len(delivered_notifications)
