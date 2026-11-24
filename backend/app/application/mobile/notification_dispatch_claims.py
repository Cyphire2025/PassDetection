"""Due notification parent claims for one bounded provider wave."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.native_push_targets import NATIVE_PROVIDERS
from app.application.mobile.push_provider import MobilePushProvider
from app.infrastructure.database.gc_mobile_models import (
    MobileNotificationModel,
    MobilePushDeliveryModel,
)


async def claim_due_push_notifications(
    session: AsyncSession, *, provider: MobilePushProvider, limit: int, current: datetime
) -> list[MobileNotificationModel]:
    """Claim the current provider's due parent rows in stable, nonwaiting order."""
    notifications = list(
        (
            await session.execute(
                select(MobileNotificationModel)
                .where(
                    MobileNotificationModel.notification_type != "group_announcement",
                    or_(
                        and_(
                            MobileNotificationModel.status == "queued",
                            or_(
                                literal(provider.name not in NATIVE_PROVIDERS),
                                ~select(MobilePushDeliveryModel.id)
                                .where(
                                    MobilePushDeliveryModel.notification_id
                                    == MobileNotificationModel.id
                                )
                                .exists(),
                                select(MobilePushDeliveryModel.id)
                                .where(
                                    MobilePushDeliveryModel.notification_id
                                    == MobileNotificationModel.id,
                                    MobilePushDeliveryModel.provider == provider.name,
                                    MobilePushDeliveryModel.status == "retry",
                                    MobilePushDeliveryModel.next_attempt_at <= current,
                                )
                                .exists(),
                            ),
                        ),
                        and_(
                            literal(provider.name in NATIVE_PROVIDERS),
                            MobileNotificationModel.status == "sent",
                            select(MobilePushDeliveryModel.id)
                            .where(
                                MobilePushDeliveryModel.notification_id
                                == MobileNotificationModel.id,
                                MobilePushDeliveryModel.provider == provider.name,
                                MobilePushDeliveryModel.status == "retry",
                                MobilePushDeliveryModel.next_attempt_at <= current,
                            )
                            .exists(),
                        ),
                    ),
                    MobileNotificationModel.available_at <= current,
                    or_(
                        MobileNotificationModel.next_push_attempt_at.is_(None),
                        MobileNotificationModel.next_push_attempt_at <= current,
                    ),
                    or_(
                        MobileNotificationModel.expires_at.is_(None),
                        MobileNotificationModel.expires_at > current,
                    ),
                )
                .order_by(
                    MobileNotificationModel.available_at.asc(),
                    MobileNotificationModel.id.asc(),
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    return notifications
