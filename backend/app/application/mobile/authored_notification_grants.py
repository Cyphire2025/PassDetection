"""Union-of-original-grants authorization for authored alerts."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.authored_notification_audience import (
    AudienceGrant,
    collect_notification_audience,
)
from app.infrastructure.database.gc_mobile_models import (
    MobileNotificationModel,
    MobilePushDeliveryModel,
)
from app.infrastructure.database.gc_notification_models import (
    GCNotificationRecipientGrantModel,
    GCNotificationRecipientModel,
)

AuthoredRecipientKey = tuple[str, uuid.UUID, uuid.UUID]


async def current_authored_grants(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    recipient_ids: Sequence[uuid.UUID],
    now: datetime,
) -> dict[uuid.UUID, list[AudienceGrant]]:
    """Compare frozen grants with freshly loaded current authority; missing means deny."""
    result: dict[uuid.UUID, list[AudienceGrant]] = {}
    ids = list(set(recipient_ids))
    for start in range(0, len(ids), 250):
        rows = (
            await session.execute(
                select(GCNotificationRecipientModel, GCNotificationRecipientGrantModel)
                .join(
                    GCNotificationRecipientGrantModel,
                    and_(
                        GCNotificationRecipientGrantModel.recipient_id
                        == GCNotificationRecipientModel.id,
                        GCNotificationRecipientGrantModel.agency_id
                        == GCNotificationRecipientModel.agency_id,
                    ),
                )
                .where(
                    GCNotificationRecipientModel.agency_id == agency_id,
                    GCNotificationRecipientModel.id.in_(ids[start : start + 250]),
                )
            )
        ).all()
        if not rows:
            continue
        snapshot = await collect_notification_audience(
            session,
            agency_id=agency_id,
            group_ids=list({grant.group_id for _, grant in rows}),
            principal_ids={grant.principal_id for _, grant in rows},
            now=now,
        )
        current = {grant.signature(): grant for grant in snapshot.grants}
        for recipient, grant in rows:
            frozen = AudienceGrant(
                agency_id,
                grant.group_id,
                grant.gc_group_access_id,
                grant.principal_id,
                recipient.recipient_type,
                recipient.person_key,
                grant.access_generation,
                grant.identity_claim_generation,
            )
            matched = current.get(frozen.signature())
            if matched is not None:
                result.setdefault(recipient.id, []).append(matched)
    return result


async def retain_authorized_authored_notifications(
    session: AsyncSession,
    *,
    notifications: list[MobileNotificationModel],
    now: datetime,
) -> list[MobileNotificationModel]:
    result = [item for item in notifications if item.notification_type != "gc_alert"]
    authored = [item for item in notifications if item.notification_type == "gc_alert"]
    from app.application.mobile.mcp_push_guard import block_unsent, origins

    mcp_origins = await origins(session, authored)
    for agency_id in {item.agency_id for item in authored}:
        scoped = [item for item in authored if item.agency_id == agency_id]
        grants = await current_authored_grants(
            session,
            agency_id=agency_id,
            recipient_ids=[
                item.authored_recipient_id
                for item in scoped
                if item.authored_recipient_id is not None
            ],
            now=now,
        )
        for item in scoped:
            allowed = (
                grants.get(item.authored_recipient_id)
                if item.authored_recipient_id is not None
                else None
            )
            if allowed and item.notification_type == "gc_alert":
                result.append(item)
                continue
            if item.id in mcp_origins:
                await block_unsent(session, item, now=now)
                continue
            item.status = "cancelled"
            item.failure_code = "recipient_access_revoked"
            item.updated_at = now
            await session.execute(
                update(MobilePushDeliveryModel)
                .where(
                    MobilePushDeliveryModel.notification_id == item.id,
                    MobilePushDeliveryModel.agency_id == agency_id,
                    MobilePushDeliveryModel.status.in_(("retry", "submitting")),
                    MobilePushDeliveryModel.provider_ticket_id.is_(None),
                )
                .values(
                    status="cancelled", last_error_code="recipient_access_revoked", updated_at=now
                )
            )
    return result
