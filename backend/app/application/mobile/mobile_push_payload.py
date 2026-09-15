"""Allowlisted tap payloads bind operational routes to the authorized recipient row."""

from __future__ import annotations

import uuid

from app.infrastructure.database.gc_mobile_models import MobileNotificationModel

_ALLOWED_PUSH_ROUTES = frozenset(
    {"trip", "documents", "qr", "updates", "readiness", "attendance", "passengers"}
)


def validated_public_payload(notification: MobileNotificationModel) -> dict[str, str]:
    payload = notification.public_payload
    if not isinstance(payload, dict) or set(payload) - {"route", "trip_id", "event_id"}:
        raise ValueError("Notification public payload was malformed")
    route = payload.get("route")
    trip_id = payload.get("trip_id")
    event_id = payload.get("event_id")
    if notification.notification_type == "gc_alert":
        if (
            notification.recipient_type != "authored"
            or notification.authored_recipient_id is None
            or route != "updates"
            or trip_id is not None
            or event_id != str(notification.id)
        ):
            raise ValueError("Authored notification public payload was out of scope")
        return {"route": "updates", "event_id": str(notification.id)}
    if route not in _ALLOWED_PUSH_ROUTES or trip_id != str(notification.group_id):
        raise ValueError("Notification public payload was out of scope")
    try:
        uuid.UUID(str(trip_id))
        if event_id is not None:
            uuid.UUID(str(event_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("Notification public payload contained an invalid identifier") from exc
    result = {"route": str(route), "trip_id": str(trip_id)}
    if event_id is not None:
        result["event_id"] = str(event_id)
    return result
