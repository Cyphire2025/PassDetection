"""Exact current device preparation for a bounded native or legacy push wave."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.mobile_push_payload import (
    validated_public_payload as _validated_public_payload,
)
from app.application.mobile.native_push_targets import (
    NATIVE_PROVIDERS,
    seed_native_delivery_targets,
)
from app.application.mobile.notification_contracts import _LOCK_SCREEN_TITLE
from app.application.mobile.notification_delivery_states import _aware_utc, _fail_delivery
from app.application.mobile.notification_registrations import (
    _load_recipient_registrations,
    _notification_recipient_key,
)
from app.application.mobile.push_provider import MobilePushMessage, MobilePushProvider
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.infrastructure.database.gc_mobile_models import (
    MobileNotificationModel,
    MobilePushDeliveryModel,
    MobilePushRegistrationModel,
)


@dataclass(frozen=True, slots=True)
class PushDispatchTargets:
    """Prepared messages and their exact mutable persistence records for this wave."""

    messages: list[MobilePushMessage]
    deliveries: list[MobilePushDeliveryModel]
    notification_by_id: dict[str, MobileNotificationModel]
    registration_by_id: dict[str, MobilePushRegistrationModel]
    delivery_by_message: dict[tuple[str, str], MobilePushDeliveryModel]


async def prepare_push_targets(
    session: AsyncSession,
    *,
    notifications: list[MobileNotificationModel],
    provider: MobilePushProvider,
    limit: int,
    current: datetime,
    max_send_attempts: int,
) -> PushDispatchTargets:
    """Prepare authorized device attempts without invoking a provider or committing."""
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
    if provider.name in NATIVE_PROVIDERS:
        await seed_native_delivery_targets(
            session,
            notifications=notifications,
            deliveries=deliveries,
            other_provider="apns" if provider.name == "fcm" else "fcm",
            now=current,
        )
    delivery_by_target = {(item.notification_id, item.registration_id): item for item in deliveries}

    registrations = await _load_recipient_registrations(
        session,
        notifications=notifications,
        provider_name=provider.name,
        now=current,
    )
    if provider.name in NATIVE_PROVIDERS:
        allowed_targets = {
            (notification.id, notification.agency_id, registration.id)
            for notification in notifications
            for registration in registrations.get(_notification_recipient_key(notification), [])
        }
        for retry_target in deliveries:
            if (
                retry_target.provider == provider.name
                and retry_target.status == "retry"
                and (
                    retry_target.notification_id,
                    retry_target.agency_id,
                    retry_target.registration_id,
                )
                not in allowed_targets
            ):
                # A logged-out/disabled device must not leave an immortal due
                # retry that repeatedly takes capacity from newer notifications.
                # These targets are definitely unsent on their next attempt.
                retry_target.status = "cancelled"
                retry_target.last_error_code = "registration_unavailable"
                retry_target.updated_at = current
    messages: list[MobilePushMessage] = []
    registration_by_id: dict[str, MobilePushRegistrationModel] = {}
    notification_by_id = {str(item.id): item for item in notifications}
    delivery_by_message: dict[tuple[str, str], MobilePushDeliveryModel] = {}
    for notification in notifications:
        key = _notification_recipient_key(notification)
        for registration in registrations.get(key, []):
            if len(messages) >= limit and provider.name not in NATIVE_PROVIDERS:
                break
            delivery = delivery_by_target.get((notification.id, registration.id))
            if delivery is not None:
                if (
                    delivery.agency_id != notification.agency_id
                    or delivery.agency_id != registration.agency_id
                    or delivery.provider != provider.name
                ):
                    _fail_delivery(delivery, current, "tenant_scope_mismatch")
                    continue
                next_attempt_at = _aware_utc(delivery.next_attempt_at)
                if (
                    delivery.status != "retry"
                    or next_attempt_at is None
                    or next_attempt_at > current
                ):
                    continue
                if delivery.send_attempts >= max_send_attempts:
                    _fail_delivery(delivery, current, "send_attempts_exhausted")
                    continue
            try:
                token = mobile_push_fernet().decrypt(registration.token_ciphertext).decode("utf-8")
                data = _validated_public_payload(notification)
            except (InvalidToken, UnicodeDecodeError):
                registration.status = "disabled"
                registration.last_failure_at = current
                registration.last_failure_code = "token_decryption_failed"
                registration.updated_at = current
                continue
            except ValueError:
                notification.status = "failed"
                notification.failure_code = "invalid_public_payload"
                notification.updated_at = current
                continue
            if delivery is None:
                delivery = MobilePushDeliveryModel(
                    id=uuid.uuid4(),
                    agency_id=notification.agency_id,
                    notification_id=notification.id,
                    registration_id=registration.id,
                    provider=provider.name,
                    status="retry",
                    send_attempts=0,
                    receipt_attempts=0,
                    next_attempt_at=current,
                )
                session.add(delivery)
                deliveries.append(delivery)
                delivery_by_target[(notification.id, registration.id)] = delivery
            if len(messages) >= limit:
                # Retain a definitely-unsent target when the HTTP wave fills up.
                # An accepted sibling may project the parent to sent; this retry
                # row keeps the remaining device discoverable on the next run.
                # It has not used a sending attempt or crossed the HTTP boundary.
                continue
            delivery.status = "submitting"
            delivery.send_attempts += 1
            delivery.last_error_code = None
            delivery.updated_at = current
            message = MobilePushMessage(
                registration_id=str(registration.id),
                notification_id=str(notification.id),
                token=token,
                title=notification.lock_screen_title or _LOCK_SCREEN_TITLE,
                body=(
                    None
                    if notification.contains_sensitive_content
                    else notification.lock_screen_body
                ),
                data=data,
                apns_environment=registration.apns_environment,
                priority="high" if notification.priority in {"high", "emergency"} else "default",
                ttl_seconds=min(
                    3600,
                    max(
                        0,
                        int(
                            (
                                (
                                    _aware_utc(notification.expires_at)
                                    or (current + timedelta(hours=1))
                                )
                                - current
                            ).total_seconds()
                        ),
                    ),
                ),
            )
            messages.append(message)
            registration_by_id[str(registration.id)] = registration
            delivery_by_message[(str(notification.id), str(registration.id))] = delivery
        if len(messages) >= limit and provider.name not in NATIVE_PROVIDERS:
            break
    return PushDispatchTargets(
        messages=messages,
        deliveries=deliveries,
        notification_by_id=notification_by_id,
        registration_by_id=registration_by_id,
        delivery_by_message=delivery_by_message,
    )
