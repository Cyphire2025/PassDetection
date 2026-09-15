"""Persist FCM send intent before crossing the non-transactional HTTP boundary.

FCM offers no per-message idempotency key or receipt lookup. A worker that dies
after sending must leave an uncertain attempt, not an automatically repeatable
queue item. This module uses a dedicated dispatch session and commits its intent
before rechecking current authorization and calling the provider.
"""

from __future__ import annotations

import hmac
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from cryptography.fernet import InvalidToken
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.announcement_push_guard import (
    retain_dispatchable_announcement_notifications,
)
from app.application.mobile.push_provider import (
    MobilePushMessage,
    MobilePushProvider,
    MobilePushTicket,
)
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.infrastructure.database.gc_mobile_models import (
    MobileNotificationModel,
    MobilePushDeliveryModel,
)

INTENT_TIMEOUT = timedelta(minutes=15)
UNKNOWN_CODE = "provider_outcome_unknown"


def mark_delivery_unknown(delivery: MobilePushDeliveryModel, now: datetime) -> None:
    if delivery.status in {"cancelled", "delivered", "provider_accepted"}:
        return
    delivery.status = "unknown"
    delivery.failed_at = None
    delivery.delivered_at = None
    delivery.last_error_code = UNKNOWN_CODE
    delivery.updated_at = now


async def recover_interrupted_fcm_intents(session: AsyncSession, *, now: datetime) -> None:
    """Bounded parent-first recovery. A live sender owns its parent row lock."""
    due = (
        MobilePushDeliveryModel.provider == "fcm",
        MobilePushDeliveryModel.status == "submitting",
        MobilePushDeliveryModel.updated_at < now - INTENT_TIMEOUT,
    )
    candidates = (
        await session.execute(
            select(MobilePushDeliveryModel.id, MobilePushDeliveryModel.notification_id)
            .where(*due)
            .order_by(MobilePushDeliveryModel.updated_at, MobilePushDeliveryModel.id)
            .limit(200)
        )
    ).all()
    if not candidates:
        return
    parents = {
        item.id: item
        for item in await session.scalars(
            select(MobileNotificationModel)
            .where(MobileNotificationModel.id.in_({row.notification_id for row in candidates}))
            .order_by(MobileNotificationModel.id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    }
    rows = list(
        await session.scalars(
            select(MobilePushDeliveryModel)
            .where(
                *due,
                MobilePushDeliveryModel.id.in_([row.id for row in candidates]),
                MobilePushDeliveryModel.notification_id.in_(parents),
            )
            .order_by(MobilePushDeliveryModel.id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    for row in rows:
        mark_delivery_unknown(row, now)
    await session.flush()
    # Imported at call time to keep the existing producer module independent.
    from app.application.mobile.notification_service import _refresh_notification_delivery_states

    await _refresh_notification_delivery_states(
        session, notifications=list(parents.values()), now=now
    )


async def send_with_durable_fcm_intents(
    session: AsyncSession,
    *,
    provider: MobilePushProvider,
    messages: list[MobilePushMessage],
    notifications: list[MobileNotificationModel],
    now: datetime,
) -> list[MobilePushTicket]:
    """Commit intent, revalidate current state, send once, leave outcome commit to caller."""
    from app.application.mobile.notification_service import (
        _load_recipient_registrations,
        _notification_recipient_key,
        _retain_currently_authorized_notifications,
        _validated_public_payload,
    )

    parent_ids = [item.id for item in notifications]
    target_keys = {(item.notification_id, item.registration_id) for item in messages}
    claims = {
        (str(item.notification_id), str(item.registration_id)): (item.id, item.send_attempts)
        for item in await session.scalars(
            select(MobilePushDeliveryModel).where(
                MobilePushDeliveryModel.notification_id.in_(parent_ids),
                MobilePushDeliveryModel.provider == "fcm",
                MobilePushDeliveryModel.status == "submitting",
            )
        )
        if (str(item.notification_id), str(item.registration_id)) in target_keys
    }
    if len(claims) != len(messages):
        raise RuntimeError("FCM intent claim was incomplete")
    # No HTTP request is made if this durable commit fails.
    await session.commit()

    # Refresh every parent the caller may project, including those without a
    # selected device. Waiting here follows the normal parent-first lock order.
    current_parents = list(
        await session.scalars(
            select(MobileNotificationModel)
            .where(MobileNotificationModel.id.in_(parent_ids))
            .order_by(MobileNotificationModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    recheck_now = max(now, datetime.now(UTC))
    eligible = [
        item
        for item in current_parents
        if item.status in {"queued", "sent"} and _is_due(item, recheck_now)
    ]
    eligible = await retain_dispatchable_announcement_notifications(
        session,
        notifications=eligible,
        now=recheck_now,
    )
    eligible = await _retain_currently_authorized_notifications(
        session,
        notifications=eligible,
        now=recheck_now,
    )
    registrations = await _load_recipient_registrations(
        session,
        notifications=eligible,
        provider_name="fcm",
        now=recheck_now,
    )
    allowed = {
        (str(item.id), str(registration.id)): registration
        for item in eligible
        for registration in registrations.get(_notification_recipient_key(item), [])
    }
    parent_by_id = {str(item.id): item for item in current_parents}
    deliveries = {
        item.id: item
        for item in await session.scalars(
            select(MobilePushDeliveryModel)
            .where(MobilePushDeliveryModel.id.in_([claim[0] for claim in claims.values()]))
            .order_by(MobilePushDeliveryModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    sendable: list[MobilePushMessage] = []
    skipped: list[MobilePushTicket] = []
    for message in messages:
        target = (message.notification_id, message.registration_id)
        delivery_id, attempt = claims[target]
        delivery = deliveries.get(delivery_id)
        parent = parent_by_id.get(message.notification_id)
        registration = allowed.get(target)
        valid = (
            delivery is not None
            and delivery.status == "submitting"
            and delivery.send_attempts == attempt
            and parent is not None
            and registration is not None
            and delivery.agency_id == parent.agency_id
            and delivery.agency_id == registration.agency_id
        )
        if valid and parent is not None and registration is not None:
            try:
                valid = (
                    hmac.compare_digest(
                        mobile_push_fernet().decrypt(registration.token_ciphertext).decode("utf-8"),
                        message.token,
                    )
                    and _validated_public_payload(parent) == message.data
                )
            except (InvalidToken, UnicodeDecodeError, ValueError):
                valid = False
        if valid and parent is not None:
            from app.application.mobile.notification_service import _aware_utc

            expiry = _aware_utc(parent.expires_at)
            remaining = max(0, int((expiry - recheck_now).total_seconds())) if expiry else 3600
            sendable.append(replace(message, ttl_seconds=min(message.ttl_seconds, remaining)))
        else:
            # This target has definitely not crossed the HTTP boundary. Current
            # cancellation/terminal state wins; a temporary source edit may retry.
            skipped.append(
                MobilePushTicket(
                    registration_id=message.registration_id,
                    notification_id=message.notification_id,
                    accepted=False,
                    retryable=bool(parent is not None and parent.status in {"queued", "sent"}),
                    error_code="source_recheck_deferred",
                    requires_receipt=False,
                )
            )
    if sendable and session.get_bind().dialect.name == "postgresql":
        # One bounded concurrent HTTP wave may take up to 30 seconds. This local
        # transaction deadline leaves result-commit time without changing the
        # database's global idle-session protection.
        await session.execute(text("SET LOCAL idle_in_transaction_session_timeout = '60000'"))
    return [*skipped, *(await provider.send(sendable) if sendable else [])]


def _is_due(notification: MobileNotificationModel, now: datetime) -> bool:
    from app.application.mobile.notification_service import _aware_utc

    available = _aware_utc(notification.available_at)
    expiry = _aware_utc(notification.expires_at)
    return (available is None or available <= now) and (expiry is None or expiry > now)
