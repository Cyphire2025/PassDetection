"""Opaque credentials and S256 PKCE; these values must never enter logs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime

PKCE_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}\Z")
PKCE_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class MCPAuthError(Exception):
    def __init__(self, error: str = "invalid_grant", status_code: int = 400):
        super().__init__(error)
        self.error = error
        self.status_code = status_code


def credential_hash(value: str, secret: str) -> str:
    return hmac.new(secret.encode(), b"gc-mcp-v1\0" + value.encode(), hashlib.sha256).hexdigest()


def new_credential(kind: str) -> str:
    return f"gcmcp_{kind}_{secrets.token_urlsafe(48)}"


def pkce_challenge(verifier: str) -> str:
    if not PKCE_VERIFIER.fullmatch(verifier):
        raise MCPAuthError()
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode()
        .rstrip("=")
    )


def utc(value: datetime) -> datetime:
    # SQLite test fixtures do not retain timezone metadata; PostgreSQL does.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
