"""Bounded push claim, target preparation and submission lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.announcement_push_guard import (
    retain_dispatchable_announcement_notifications,
)
from app.application.mobile.fcm_dispatch_intents import (
    recover_interrupted_fcm_intents,
    send_with_durable_fcm_intents,
)
from app.application.mobile.mcp_push_guard import one_origin_wave
from app.application.mobile.native_push_targets import NATIVE_PROVIDERS
from app.application.mobile.notification_authority import _retain_currently_authorized_notifications
from app.application.mobile.notification_delivery_states import (
    _refresh_notification_delivery_states,
)
from app.application.mobile.notification_dispatch_claims import claim_due_push_notifications
from app.application.mobile.notification_dispatch_results import apply_push_tickets
from app.application.mobile.notification_dispatch_targets import prepare_push_targets
from app.application.mobile.push_provider import MobilePushProvider


async def dispatch_mobile_push_batch(
    session: AsyncSession,
    *,
    provider: MobilePushProvider,
    limit: int,
    now: datetime | None = None,
    max_send_attempts: int = 5,
    retry_base_seconds: int = 5,
    receipt_initial_delay_seconds: int = 900,
) -> int:
    """Submit a bounded batch and durably retain every provider ticket.

    FCM requires a dedicated worker session: its send intent commits before HTTP
    so a worker interruption cannot silently turn a possible send into a retry.
    """

    if not provider.enabled:
        return 0
    if limit < 1 or limit > 100:
        raise ValueError("Mobile push batch limit must be between 1 and 100")
    # FCM uses individual HTTP requests. One concurrent wave bounds how long
    # authorization/source locks are held and avoids idle transaction expiry.
    if provider.name in NATIVE_PROVIDERS:
        limit = min(limit, 20)
    if max_send_attempts < 1:
        raise ValueError("Mobile push send attempts must be positive")
    if retry_base_seconds < 1 or receipt_initial_delay_seconds < 1:
        raise ValueError("Mobile push retry delays must be positive")
    if (
        provider.name in NATIVE_PROVIDERS
        and (prepare := getattr(provider, "prepare", None)) is not None
    ):
        # Obtain OAuth outside the source/access lock transaction.
        await prepare()
    current = now or datetime.now(tz=UTC)
    if provider.name in NATIVE_PROVIDERS:
        await recover_interrupted_fcm_intents(session, now=current, provider_name=provider.name)
    notifications = await claim_due_push_notifications(
        session, provider=provider, limit=limit, current=current
    )
    if not notifications:
        return 0
    notifications = await one_origin_wave(
        session, notifications, now=current, provider=provider.name
    )
    notifications = await retain_dispatchable_announcement_notifications(
        session,
        notifications=notifications,
        now=current,
    )
    if not notifications:
        return 0
    notifications = await _retain_currently_authorized_notifications(
        session,
        notifications=notifications,
        now=current,
    )
    if not notifications:
        return 0

    targets = await prepare_push_targets(
        session,
        notifications=notifications,
        provider=provider,
        limit=limit,
        current=current,
        max_send_attempts=max_send_attempts,
    )
    messages = targets.messages
    deliveries = targets.deliveries
    if not messages:
        await session.flush()
        await _refresh_notification_delivery_states(
            session,
            notifications=notifications,
            now=current,
        )
        for notification in notifications:
            if notification.status == "queued" and not any(
                item.notification_id == notification.id for item in deliveries
            ):
                notification.failure_code = "no_active_registration"
                notification.next_push_attempt_at = current + timedelta(minutes=5)
                notification.updated_at = current
        return 0

    await session.flush()
    tickets = (
        await send_with_durable_fcm_intents(
            session,
            provider=provider,
            messages=messages,
            notifications=notifications,
            now=current,
        )
        if provider.name in NATIVE_PROVIDERS
        else await provider.send(messages)
    )
    submitted_notifications = apply_push_tickets(
        tickets,
        targets,
        provider=provider,
        current=current,
        max_send_attempts=max_send_attempts,
        retry_base_seconds=retry_base_seconds,
        receipt_initial_delay_seconds=receipt_initial_delay_seconds,
    )
    await session.flush()
    await _refresh_notification_delivery_states(
        session,
        notifications=notifications,
        now=current,
    )
    return len(submitted_notifications)
