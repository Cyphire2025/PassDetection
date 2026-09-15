"""Union-of-original-grants authorization for authored alert feeds and workers."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, undefer

from app.application.mobile.authored_notification_audience import (
    AudienceGrant,
    collect_notification_audience,
)
from app.core.config.settings import get_settings
from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobileNotificationModel,
    MobilePassengerSessionIdentityModel,
    MobilePushDeliveryModel,
    MobilePushRegistrationModel,
)
from app.infrastructure.database.gc_notification_models import (
    GCNotificationRecipientGrantModel,
    GCNotificationRecipientModel,
)

AuthoredRecipientKey = tuple[str, uuid.UUID, uuid.UUID]


def authored_notification_recipient_key(
    notification: MobileNotificationModel,
) -> AuthoredRecipientKey:
    if notification.notification_type != "gc_alert" or notification.authored_recipient_id is None:
        raise ValueError("Malformed authored notification")
    return ("authored", notification.authored_recipient_id, notification.agency_id)


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


async def registrations_for_grants(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    grants: Sequence[AudienceGrant],
    provider_name: str,
    now: datetime,
    target_keys: dict[tuple[str, ...], set[str]] | None = None,
) -> dict[str, list[MobilePushRegistrationModel]]:
    """Each registration must have a current exact original principal/session grant."""
    if not grants:
        return {}
    grants_by_principal: dict[uuid.UUID, list[AudienceGrant]] = {}
    for grant in grants:
        grants_by_principal.setdefault(grant.principal_id, []).append(grant)
    ids = list(grants_by_principal)
    result: dict[str, dict[str, MobilePushRegistrationModel]] = {}
    for start in range(0, len(ids), 250):
        page = ids[start : start + 250]
        binding_exists = (
            select(MobilePassengerSessionIdentityModel.session_id)
            .where(
                MobilePassengerSessionIdentityModel.session_id == MobileDeviceSessionModel.id,
                MobilePassengerSessionIdentityModel.agency_id == agency_id,
                MobilePassengerSessionIdentityModel.passenger_identity_id.in_(page),
            )
            .exists()
        )
        rows = (
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
                    MobilePushRegistrationModel.agency_id == agency_id,
                    MobilePushRegistrationModel.provider == provider_name,
                    MobilePushRegistrationModel.platform
                    == ("ios" if provider_name == "apns" else "android"),
                    MobilePushRegistrationModel.environment
                    == ("production" if get_settings().is_production else "development"),
                    MobilePushRegistrationModel.app_bundle_id
                    == "com.globalconnects.groupcompanion",
                    MobilePushRegistrationModel.status == "active",
                    MobilePushRegistrationModel.notifications_authorized.is_(True),
                    MobileDeviceSessionModel.status == "active",
                    MobileDeviceSessionModel.revoked_at.is_(None),
                    MobileDeviceSessionModel.expires_at > now,
                    or_(
                        and_(MobileDeviceSessionModel.subject_role == "passenger", binding_exists),
                        and_(
                            MobileDeviceSessionModel.subject_role.in_(
                                ("client_manager", "coordinator")
                            ),
                            MobileDeviceSessionModel.user_id.in_(page),
                        ),
                    ),
                )
                .order_by(
                    MobilePushRegistrationModel.last_registered_at.desc(),
                    MobilePushRegistrationModel.id,
                )
                .execution_options(populate_existing=True)
            )
        ).all()
        bindings = await _session_bindings(session, agency_id, [device.id for _, device in rows])
        for registration, device in rows:
            if provider_name == "apns" and registration.apns_environment not in {
                "development",
                "production",
            }:
                continue
            device_grants = _device_grants(device, bindings.get(device.id, []), grants_by_principal)
            for grant in device_grants:
                # Prefer newest registration per physical installation, across trip switches.
                keys = (
                    target_keys.get(grant.signature(), set())
                    if target_keys is not None
                    else {grant.person_key}
                )
                for key in keys:
                    result.setdefault(key, {}).setdefault(
                        device.device_identifier_hash, registration
                    )
    return {key: list(values.values()) for key, values in result.items()}


async def _session_bindings(
    session: AsyncSession, agency_id: uuid.UUID, ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[MobilePassengerSessionIdentityModel]]:
    result: dict[uuid.UUID, list[MobilePassengerSessionIdentityModel]] = {}
    for start in range(0, len(ids), 250):
        rows = (
            await session.execute(
                select(MobilePassengerSessionIdentityModel)
                .where(
                    MobilePassengerSessionIdentityModel.agency_id == agency_id,
                    MobilePassengerSessionIdentityModel.session_id.in_(ids[start : start + 250]),
                )
                .execution_options(populate_existing=True)
            )
        ).scalars()
        for row in rows:
            result.setdefault(row.session_id, []).append(row)
    return result


def _device_grants(
    device: MobileDeviceSessionModel,
    bindings: list[MobilePassengerSessionIdentityModel],
    grants: dict[uuid.UUID, list[AudienceGrant]],
) -> list[AudienceGrant]:
    if device.subject_role != "passenger":
        return (
            [grant for grant in grants.get(device.user_id, []) if grant.role == device.subject_role]
            if device.user_id
            else []
        )
    return [
        grant
        for binding in bindings
        for grant in grants.get(binding.passenger_identity_id, [])
        if grant.role == "passenger"
        and binding.agency_id == grant.agency_id
        and binding.group_id == grant.group_id
        and binding.gc_group_access_id == grant.access_id
        and binding.identity_claim_generation == grant.claim_generation
    ]


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
    return await _exclude_rotated_installation_attempts(session, notifications, result)


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
