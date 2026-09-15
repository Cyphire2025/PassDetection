"""Prepare both native transports before either can mark their shared parent sent."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import (
    MobileNotificationModel,
    MobilePushDeliveryModel,
)

NATIVE_PROVIDERS = frozenset({"fcm", "apns"})


async def seed_native_delivery_targets(
    session: AsyncSession,
    *,
    notifications: list[MobileNotificationModel],
    deliveries: list[MobilePushDeliveryModel],
    other_provider: str,
    now: datetime,
) -> None:
    """Keep definitely-unsent iOS/Android siblings discoverable after other devices accept.

    The caller owns parent locks. No HTTP, attempt increment or token disclosure occurs here.
    Disabled transports can later consume these rows within the original notification expiry.
    """
    from app.application.mobile.notification_service import (
        _load_recipient_registrations,
        _notification_recipient_key,
    )

    registrations = await _load_recipient_registrations(
        session, notifications=notifications, provider_name=other_provider, now=now
    )
    existing = {(item.notification_id, item.registration_id) for item in deliveries}
    for notification in notifications:
        for registration in registrations.get(_notification_recipient_key(notification), []):
            if (notification.id, registration.id) in existing:
                continue
            delivery = MobilePushDeliveryModel(
                id=uuid.uuid4(),
                agency_id=notification.agency_id,
                notification_id=notification.id,
                registration_id=registration.id,
                provider=other_provider,
                status="retry",
                send_attempts=0,
                receipt_attempts=0,
                next_attempt_at=now,
            )
            session.add(delivery)
            deliveries.append(delivery)
            existing.add((notification.id, registration.id))
