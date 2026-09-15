"""Claim receipt work in the same parent-first lock order as push dispatch."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import (
    MobileNotificationModel,
    MobilePushDeliveryModel,
)


async def claim_mobile_push_receipts(
    session: AsyncSession,
    *,
    provider_name: str,
    limit: int,
    now: datetime,
) -> tuple[list[MobilePushDeliveryModel], dict[uuid.UUID, MobileNotificationModel]]:
    """Fence receipt projection against cancellation without reversing row locks.

    A receipt previously locked its delivery before reading a cached parent.
    Cancellation could commit during the provider await and then be overwritten.
    Claim current parents first and retain those locks through the caller's
    receipt transaction. Competing dispatch/cancellation work is skipped.
    """
    due = (
        MobilePushDeliveryModel.provider == provider_name,
        MobilePushDeliveryModel.status == "receipt_pending",
        MobilePushDeliveryModel.next_attempt_at <= now,
        MobilePushDeliveryModel.provider_ticket_id.is_not(None),
    )
    candidates = (
        await session.execute(
            select(MobilePushDeliveryModel.id, MobilePushDeliveryModel.notification_id)
            .where(*due)
            .order_by(MobilePushDeliveryModel.next_attempt_at, MobilePushDeliveryModel.id)
            .limit(limit)
        )
    ).all()
    if not candidates:
        return [], {}
    parent_ids = {row.notification_id for row in candidates}
    notifications = {
        item.id: item
        for item in (
            await session.scalars(
                select(MobileNotificationModel)
                .where(MobileNotificationModel.id.in_(parent_ids))
                .order_by(MobileNotificationModel.id)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        )
    }
    omitted_ids = parent_ids - notifications.keys()
    # Normally foreign keys prevent missing parents. Preserve the existing
    # tenant/missing-parent failure path for legacy inconsistencies, while a
    # merely locked parent must be deferred and never mistaken for an orphan.
    existing_omitted = (
        set(
            await session.scalars(
                select(MobileNotificationModel.id).where(
                    MobileNotificationModel.id.in_(omitted_ids)
                )
            )
        )
        if omitted_ids
        else set()
    )
    claimable_ids = [row.id for row in candidates if row.notification_id not in existing_omitted]
    if not claimable_ids:
        return [], notifications
    deliveries = list(
        await session.scalars(
            select(MobilePushDeliveryModel)
            .where(
                MobilePushDeliveryModel.id.in_(claimable_ids),
                MobilePushDeliveryModel.notification_id.in_(parent_ids - existing_omitted),
                *due,
            )
            .order_by(MobilePushDeliveryModel.next_attempt_at, MobilePushDeliveryModel.id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    return deliveries, notifications
