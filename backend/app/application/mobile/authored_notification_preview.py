"""Short-lived signed audience reviews, independent of provider credentials."""

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime

from fastapi import HTTPException

from app.core.config.settings import get_settings


def _signature(value: bytes) -> str:
    secret = get_settings().app_secret_key.encode()
    return hmac.new(secret, b"gc-notification-preview:v1:" + value, hashlib.sha256).hexdigest()


def create_preview_token(
    *,
    agency_id: uuid.UUID,
    actor_id: uuid.UUID,
    draft_id: uuid.UUID,
    revision: int,
    fingerprint: str,
    expires_at: datetime,
) -> str:
    payload = json.dumps(
        {
            "agency": str(agency_id),
            "actor": str(actor_id),
            "draft": str(draft_id),
            "revision": revision,
            "audience": fingerprint,
            "expires": int(expires_at.timestamp()),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + _signature(payload)


def read_preview_token(
    token: str, *, agency_id: uuid.UUID, actor_id: uuid.UUID, draft_id: uuid.UUID, revision: int
) -> tuple[str, int]:
    try:
        encoded, signature = token.split(".")
        payload = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
        )
        if not hmac.compare_digest(_signature(payload), signature):
            raise ValueError("signature")
        value = json.loads(payload)
        if any(
            value.get(key) != expected
            for key, expected in (
                ("agency", str(agency_id)),
                ("actor", str(actor_id)),
                ("draft", str(draft_id)),
                ("revision", revision),
            )
        ):
            raise ValueError("scope")
        fingerprint = value["audience"]
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise ValueError("audience")
        return fingerprint, int(value["expires"])
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "stale_preview") from exc


def request_fingerprint(
    *, draft_id: uuid.UUID, revision: int, audience: str, actor_id: uuid.UUID
) -> str:
    return hashlib.sha256(f"{draft_id}:{revision}:{audience}:{actor_id}".encode()).hexdigest()


def provider_readiness() -> dict[str, bool]:
    settings = get_settings()
    android = settings.mobile.enabled and settings.mobile.push_provider == "fcm"
    ios = settings.mobile.enabled and settings.mobile.push_apns_enabled
    return {
        "provider_enabled": android or ios,
        "android_provider_enabled": android,
        "ios_provider_enabled": ios,
    }
