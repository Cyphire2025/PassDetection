"""Recheck notification grants and cancel definitely-unsent work."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.notification_group_authority import (
    currently_authorized_group_recipients,
)
from app.infrastructure.database.gc_mobile_models import (
    MobileNotificationModel,
    MobilePushDeliveryModel,
)


async def _retain_currently_authorized_notifications(
    session: AsyncSession,
    *,
    notifications: list[MobileNotificationModel],
    now: datetime,
) -> list[MobileNotificationModel]:
    """Cancel due group pushes whose recipient no longer has trip access."""

    from app.application.mobile.authored_notification_access import (
        retain_authorized_authored_notifications,
    )

    notifications = await retain_authorized_authored_notifications(
        session, notifications=notifications, now=now
    )

    grouped = [
        item
        for item in notifications
        if item.gc_group_access_id is not None and item.group_id is not None
    ]
    if not grouped:
        return notifications

    eligible = await currently_authorized_group_recipients(session, grouped=grouped, now=now)

    retained: list[MobileNotificationModel] = []
    cancelled_ids: list[uuid.UUID] = []
    for item in notifications:
        if item.gc_group_access_id is None or item.group_id is None:
            retained.append(item)
            continue
        principal_id = (
            item.recipient_passenger_identity_id
            if item.recipient_type == "passenger"
            else item.recipient_user_id
        )
        key = (
            item.recipient_type,
            item.agency_id,
            item.gc_group_access_id,
            item.group_id,
            principal_id,
        )
        if principal_id is not None and key in eligible:
            retained.append(item)
            continue
        item.status = "cancelled"
        item.failure_code = "recipient_access_revoked"
        item.updated_at = now
        cancelled_ids.append(item.id)
    if cancelled_ids:
        await session.execute(
            update(MobilePushDeliveryModel)
            .where(
                MobilePushDeliveryModel.notification_id.in_(cancelled_ids),
                MobilePushDeliveryModel.status.in_(("submitting", "retry")),
            )
            .values(
                status="cancelled",
                last_error_code="recipient_access_revoked",
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
    return retained
