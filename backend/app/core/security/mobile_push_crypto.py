"""Key-derived encryption for mobile push registration tokens.

Push tokens are bearer-like routing credentials.  The database stores a
lookup hash for uniqueness and an application-encrypted value for the worker
that must deliver a notification.  Key material is never stored with the
registration row.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet

from app.core.config.settings import Settings, get_settings


def mobile_push_fernet(settings: Settings | None = None) -> Fernet:
    """Return the version-one push-token cipher for this deployment."""

    resolved = settings or get_settings()
    configured = resolved.mobile.jwt_secret_key
    if configured is not None:
        base = configured.get_secret_value().encode("utf-8")
    else:
        if resolved.is_production and resolved.mobile.enabled:
            raise RuntimeError(
                "MOBILE_JWT_SECRET_KEY is required to encrypt mobile push tokens"
            )
        base = resolved.app_secret_key.encode("utf-8")
    derived = hmac.new(
        base,
        b"gc-mobile:push-token-encryption:v1",
        hashlib.sha256,
    ).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


__all__ = ["mobile_push_fernet"]
