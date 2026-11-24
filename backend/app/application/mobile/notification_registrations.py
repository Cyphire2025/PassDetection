"""Load exact current device targets for authorized notifications."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer
from sqlalchemy.sql.elements import ColumnElement

from app.application.mobile.native_push_targets import NATIVE_PROVIDERS
from app.application.mobile.passenger_notification_authority import (
    authoritative_passenger_device_ids,
)
from app.core.config.settings import get_settings
from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobileNotificationModel,
    MobilePushRegistrationModel,
)


async def _load_recipient_registrations(
    session: AsyncSession,
    *,
    notifications: list[MobileNotificationModel],
    provider_name: str,
    now: datetime,
) -> dict[tuple[str, uuid.UUID, uuid.UUID], list[MobilePushRegistrationModel]]:
    from app.application.mobile.authored_notification_access import (
        load_authored_recipient_registrations,
    )

    authored = await load_authored_recipient_registrations(
        session, notifications=notifications, provider_name=provider_name, now=now
    )
    user_ids = {
        item.recipient_user_id for item in notifications if item.recipient_user_id is not None
    }
    passenger_ids = {
        item.recipient_passenger_identity_id
        for item in notifications
        if item.recipient_passenger_identity_id is not None
    }
    if not user_ids and not passenger_ids:
        return authored
    provider_scope: tuple[ColumnElement[bool], ...] = (
        (
            MobilePushRegistrationModel.platform
            == ("android" if provider_name == "fcm" else "ios"),
            MobilePushRegistrationModel.environment
            == ("production" if get_settings().is_production else "development"),
            MobilePushRegistrationModel.app_bundle_id == "com.globalconnects.groupcompanion",
        )
        if provider_name in NATIVE_PROVIDERS
        else ()
    )
    if provider_name == "apns":
        provider_scope += (
            MobilePushRegistrationModel.apns_environment.in_(("development", "production")),
        )
    recipient_filter = or_(
        and_(
            MobileDeviceSessionModel.subject_role.in_(("client_manager", "coordinator")),
            MobileDeviceSessionModel.user_id.in_(user_ids),
        ),
        and_(
            MobileDeviceSessionModel.subject_role == "passenger",
            MobileDeviceSessionModel.passenger_identity_id.in_(passenger_ids),
        ),
    )
    rows = list(
        (
            await session.execute(
                select(MobilePushRegistrationModel, MobileDeviceSessionModel)
                .options(undefer(MobilePushRegistrationModel.token_ciphertext))
                .join(
                    MobileDeviceSessionModel,
                    and_(
                        MobileDeviceSessionModel.id == MobilePushRegistrationModel.session_id,
                        MobileDeviceSessionModel.agency_id == MobilePushRegistrationModel.agency_id,
                    ),
                )
                .where(
                    MobilePushRegistrationModel.provider == provider_name,
                    *provider_scope,
                    MobilePushRegistrationModel.status == "active",
                    MobilePushRegistrationModel.notifications_authorized.is_(True),
                    MobileDeviceSessionModel.status == "active",
                    MobileDeviceSessionModel.revoked_at.is_(None),
                    MobileDeviceSessionModel.expires_at > now,
                    recipient_filter,
                )
                .order_by(MobilePushRegistrationModel.last_registered_at.desc())
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    allowed_devices = await authoritative_passenger_device_ids(
        session, [device for _, device in rows]
    )
    result: dict[
        tuple[str, uuid.UUID, uuid.UUID],
        list[MobilePushRegistrationModel],
    ] = authored
    for registration, device_session in rows:
        if device_session.subject_role == "passenger" and device_session.id not in allowed_devices:
            continue
        principal_id = (
            device_session.passenger_identity_id
            if device_session.subject_role == "passenger"
            else device_session.user_id
        )
        if principal_id is None:
            continue
        key = (device_session.subject_role, principal_id, device_session.agency_id)
        result.setdefault(key, []).append(registration)
    return result


def _notification_recipient_key(
    notification: MobileNotificationModel,
) -> tuple[str, uuid.UUID, uuid.UUID]:
    if notification.recipient_type == "authored" and notification.authored_recipient_id is not None:
        return ("authored", notification.authored_recipient_id, notification.agency_id)
    principal_id = (
        notification.recipient_passenger_identity_id
        if notification.recipient_type == "passenger"
        else notification.recipient_user_id
    )
    if principal_id is None:
        raise ValueError("Notification recipient was malformed")
    return (notification.recipient_type, principal_id, notification.agency_id)
