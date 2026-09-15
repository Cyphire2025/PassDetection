"""Bounded ES256 APNs authentication; key material never enters logs or the database."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config.settings import MobileSettings

_lock = threading.Lock()
_cached: tuple[tuple[str, str, str, int, int], float, str] | None = None


class ApnsCredentialError(Exception):
    """Safe, bounded credential error without file or secret contents."""


def apns_access_token(settings: MobileSettings) -> str:
    global _cached
    if (
        not settings.push_apns_key_file
        or not settings.push_apns_key_id
        or not settings.push_apns_team_id
    ):
        raise ApnsCredentialError("apns_credentials_unavailable")
    try:
        path = Path(settings.push_apns_key_file)
        stat = path.stat()
        if not path.is_file() or not 1 <= stat.st_size <= 16_384:
            raise ApnsCredentialError("apns_credentials_unavailable")
        cache_key = (
            str(path),
            settings.push_apns_key_id,
            settings.push_apns_team_id,
            stat.st_mtime_ns,
            stat.st_size,
        )
        with _lock:
            now = time.time()
            # Apple tokens expire after one hour. Reuse for 50 minutes, including across batches.
            if _cached is not None and _cached[0] == cache_key and 0 <= now - _cached[1] < 3000:
                return _cached[2]
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
                key.curve, ec.SECP256R1
            ):
                raise ApnsCredentialError("apns_credentials_unavailable")
            token = jwt.encode(
                {"iss": settings.push_apns_team_id, "iat": int(now)},
                key,
                algorithm="ES256",
                headers={"kid": settings.push_apns_key_id},
            )
            _cached = (cache_key, now, token)
            return token
    except (OSError, ValueError, TypeError, jwt.PyJWTError) as exc:
        raise ApnsCredentialError("apns_credentials_unavailable") from exc
