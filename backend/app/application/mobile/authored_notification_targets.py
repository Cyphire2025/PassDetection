"""Frozen authored recipient targeting and rotated-attempt fences."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.application.mobile.authored_notification_grants import (
    AuthoredRecipientKey,
    current_authored_grants,
)
from app.application.mobile.authored_notification_registrations import registrations_for_grants
from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobileNotificationModel,
    MobilePushDeliveryModel,
    MobilePushRegistrationModel,
)


def authored_notification_recipient_key(
    notification: MobileNotificationModel,
) -> AuthoredRecipientKey:
    if notification.notification_type != "gc_alert" or notification.authored_recipient_id is None:
        raise ValueError("Malformed authored notification")
    return ("authored", notification.authored_recipient_id, notification.agency_id)


async def load_authored_recipient_registrations(
    session: AsyncSession,
    *,
    notifications: list[MobileNotificationModel],
    provider_name: str,
    now: datetime,
) -> dict[AuthoredRecipientKey, list[MobilePushRegistrationModel]]:
    result: dict[AuthoredRecipientKey, list[MobilePushRegistrationModel]] = {}
    for agency_id in {item.agency_id for item in notifications}:
        scoped = [item for item in notifications if item.agency_id == agency_id]
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
        target_keys: dict[tuple[str, ...], set[str]] = {}
        for recipient_id, recipient_grants in grants.items():
            for grant in recipient_grants:
                target_keys.setdefault(grant.signature(), set()).add(str(recipient_id))
        registrations = await registrations_for_grants(
            session,
            agency_id=agency_id,
            grants=[grant for values in grants.values() for grant in values],
            provider_name=provider_name,
            now=now,
            target_keys=target_keys,
        )
        for item in scoped:
            allowed = grants.get(item.authored_recipient_id) if item.authored_recipient_id else None
            if allowed:
                result[authored_notification_recipient_key(item)] = registrations.get(
                    str(item.authored_recipient_id), []
                )
    from app.application.mobile.mcp_push_guard import frozen_registrations

    result = await _exclude_rotated_installation_attempts(session, notifications, result)
    return await frozen_registrations(session, notifications, result)


async def _exclude_rotated_installation_attempts(
    session: AsyncSession,
    notifications: list[MobileNotificationModel],
    registrations: dict[AuthoredRecipientKey, list[MobilePushRegistrationModel]],
) -> dict[AuthoredRecipientKey, list[MobilePushRegistrationModel]]:
    """A new token/session must not create a second uncertain/accepted device attempt.

    Current registration intents remain eligible for their durable final recheck.
    Only a DIFFERENT registration for the same physical installation fences a
    new attempt. Explicit provider rejections/retries may use the replacement.
    """
    ids = list({row.id for rows in registrations.values() for row in rows})
    if not ids:
        return registrations
    old_registration = aliased(MobilePushRegistrationModel)
    old_device = aliased(MobileDeviceSessionModel)
    blocked: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for start in range(0, len(ids), 250):
        rows = (
            await session.execute(
                select(MobilePushDeliveryModel.notification_id, MobilePushRegistrationModel.id)
                .join(
                    old_registration,
                    and_(
                        old_registration.id == MobilePushDeliveryModel.registration_id,
                        old_registration.agency_id == MobilePushDeliveryModel.agency_id,
                    ),
                )
                .join(
                    old_device,
                    and_(
                        old_device.id == old_registration.session_id,
                        old_device.agency_id == old_registration.agency_id,
                    ),
                )
                .join(
                    MobileDeviceSessionModel,
                    and_(
                        MobileDeviceSessionModel.agency_id == old_device.agency_id,
                        MobileDeviceSessionModel.device_identifier_hash
                        == old_device.device_identifier_hash,
                        MobileDeviceSessionModel.platform == old_device.platform,
                    ),
                )
                .join(
                    MobilePushRegistrationModel,
                    and_(
                        MobilePushRegistrationModel.session_id == MobileDeviceSessionModel.id,
                        MobilePushRegistrationModel.agency_id == MobileDeviceSessionModel.agency_id,
                        MobilePushRegistrationModel.app_bundle_id == old_registration.app_bundle_id,
                    ),
                )
                .where(
                    MobilePushDeliveryModel.notification_id.in_(
                        [item.id for item in notifications]
                    ),
                    MobilePushRegistrationModel.id.in_(ids[start : start + 250]),
                    old_registration.id != MobilePushRegistrationModel.id,
                    MobilePushDeliveryModel.status.in_(
                        (
                            "submitting",
                            "unknown",
                            "provider_accepted",
                            "delivered",
                            "receipt_pending",
                        )
                    ),
                )
            )
        ).all()
        blocked.update(
            (notification_id, registration_id) for notification_id, registration_id in rows
        )
    notification_ids = {
        authored_notification_recipient_key(item): item.id
        for item in notifications
        if item.notification_type == "gc_alert"
    }
    return {
        key: [row for row in rows if (notification_ids[key], row.id) not in blocked]
        for key, rows in registrations.items()
    }
