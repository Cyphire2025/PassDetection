"""Deterministic, public-safe trip countdown content."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime
from typing import Literal

from app.application.mobile.notification_contracts import (
    _COUNTDOWN_NOTIFICATION_TYPE,
    _COUNTDOWN_TEMPLATES,
)
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel


def _countdown_notification_values(
    *,
    recipient_id: uuid.UUID,
    recipient_type: Literal["passenger", "client_manager", "coordinator"],
    access: GCGroupAccessModel,
    travel_date: date,
    timezone_name: str,
    days_remaining: int,
    available_at: datetime,
    expires_at: datetime,
) -> dict[str, object]:
    templates = _COUNTDOWN_TEMPLATES[days_remaining]
    seed = (
        f"{access.group_id}:{recipient_id}:{travel_date.isoformat()}:"
        f"{timezone_name}:{days_remaining}"
    ).encode("ascii")
    template_index = int.from_bytes(hashlib.sha256(seed).digest()[:2], "big") % len(templates)
    title, body = templates[template_index]
    is_passenger = recipient_type == "passenger"
    return {
        "id": uuid.uuid4(),
        "agency_id": access.agency_id,
        "group_id": access.group_id,
        "gc_group_access_id": access.id,
        "recipient_type": recipient_type,
        "recipient_user_id": None if is_passenger else recipient_id,
        "recipient_passenger_identity_id": recipient_id if is_passenger else None,
        "notification_type": _COUNTDOWN_NOTIFICATION_TYPE,
        "category": "itinerary",
        "priority": "normal",
        "title": title,
        "body": body,
        "lock_screen_title": title,
        "lock_screen_body": body,
        "contains_sensitive_content": False,
        "deep_link_path": f"/trip?trip_id={access.group_id}",
        "dedupe_key": (
            f"trip-countdown:{travel_date.isoformat()}:{timezone_name}:{days_remaining}"
        ),
        "public_payload": {"route": "trip", "trip_id": str(access.group_id)},
        "status": "queued",
        "available_at": available_at,
        "expires_at": expires_at,
    }
