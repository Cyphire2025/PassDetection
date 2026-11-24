"""Provider ticket outcomes, retries and missing-target handling."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.application.mobile.fcm_dispatch_intents import mark_delivery_unknown
from app.application.mobile.native_push_targets import NATIVE_PROVIDERS
from app.application.mobile.notification_delivery_states import (
    _bounded_backoff_seconds,
    _fail_delivery,
    _retry_delivery,
    _revoke_registration,
)
from app.application.mobile.notification_dispatch_targets import PushDispatchTargets
from app.application.mobile.push_provider import MobilePushProvider, MobilePushTicket
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)


def apply_push_tickets(
    tickets: list[MobilePushTicket],
    targets: PushDispatchTargets,
    *,
    provider: MobilePushProvider,
    current: datetime,
    max_send_attempts: int,
    retry_base_seconds: int,
    receipt_initial_delay_seconds: int,
) -> set[str]:
    """Apply only exact returned targets and preserve accepted/uncertain evidence."""
    notification_by_id = targets.notification_by_id
    registration_by_id = targets.registration_by_id
    delivery_by_message = targets.delivery_by_message
    submitted_notifications: set[str] = set()
    returned_targets: set[tuple[str, str]] = set()
    for ticket in tickets:
        ticket_notification = notification_by_id.get(ticket.notification_id)
        ticket_registration = registration_by_id.get(ticket.registration_id)
        delivery = delivery_by_message.get((ticket.notification_id, ticket.registration_id))
        if ticket_notification is None or ticket_registration is None or delivery is None:
            continue
        returned_targets.add((ticket.notification_id, ticket.registration_id))
        if ticket.accepted and ticket.provider_ticket_id is not None:
            submitted_notifications.add(ticket.notification_id)
            delivery.provider_ticket_id = ticket.provider_ticket_id
            delivery.status = "receipt_pending" if ticket.requires_receipt else "provider_accepted"
            delivery.submitted_at = current
            delivery.next_attempt_at = current + timedelta(seconds=receipt_initial_delay_seconds)
            delivery.last_error_code = None
            record_operational_event(OperationalEvent.MOBILE_PUSH, "ticket_accepted")
        elif ticket.outcome_unknown:
            mark_delivery_unknown(delivery, current)
            record_operational_event(OperationalEvent.MOBILE_PUSH, "send_outcome_unknown")
        else:
            code = ticket.error_code or "provider_ticket_error"
            ticket_registration.last_failure_at = current
            ticket_registration.last_failure_code = code
            if code == "DeviceNotRegistered":
                _revoke_registration(ticket_registration, current, code)
                _fail_delivery(delivery, current, code)
                record_operational_event(OperationalEvent.MOBILE_PUSH, "device_revoked")
            elif ticket.retryable and delivery.send_attempts < max_send_attempts:
                _retry_delivery(
                    delivery,
                    current,
                    code,
                    delay_seconds=max(
                        _bounded_backoff_seconds(retry_base_seconds, delivery.send_attempts),
                        min(3600, max(0, ticket.retry_after_seconds or 0)),
                    ),
                )
                record_operational_event(
                    OperationalEvent.MOBILE_PUSH,
                    "send_retry_scheduled",
                )
            else:
                _fail_delivery(delivery, current, code)
                record_operational_event(OperationalEvent.MOBILE_PUSH, "send_failed")
        ticket_registration.updated_at = current

    for target, delivery in delivery_by_message.items():
        if target in returned_targets:
            continue
        if provider.name in NATIVE_PROVIDERS:
            mark_delivery_unknown(delivery, current)
            continue
        if delivery.send_attempts < max_send_attempts:
            _retry_delivery(
                delivery,
                current,
                "provider_missing_ticket",
                delay_seconds=_bounded_backoff_seconds(
                    retry_base_seconds,
                    delivery.send_attempts,
                ),
            )
            record_operational_event(
                OperationalEvent.MOBILE_PUSH,
                "send_retry_scheduled",
            )
        else:
            _fail_delivery(delivery, current, "provider_missing_ticket")
            record_operational_event(OperationalEvent.MOBILE_PUSH, "send_failed")
    return submitted_notifications
