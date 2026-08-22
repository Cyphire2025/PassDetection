"""
JWT Token Management
====================
Creates and verifies JSON Web Tokens for access and refresh flows.

Design:
  - Access tokens: short-lived (30 min), carry user identity + role.
  - Refresh tokens: long-lived (7 days), stored as opaque UUIDs in DB.
    The JWT is only used for the access token; refresh tokens are
    looked up in the database so they can be revoked.
  - All token operations are stateless on the access token side.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from app.core.config.settings import get_settings
from app.domain.exceptions.exceptions import AuthenticationError, TokenExpiredError

_settings = get_settings()

# ── Token Type Constants ──────────────────────────────────────────────────────

TOKEN_TYPE_ACCESS  = "access"
TOKEN_TYPE_REFRESH = "refresh"


# ── Token Creation ────────────────────────────────────────────────────────────

def create_access_token(
    user_id: uuid.UUID,
    role: str,
    agency_id: uuid.UUID | None = None,
    *,
    session_version: int = 1,
    authentication_methods: tuple[str, ...] = ("pwd",),
    mfa_authenticated_at: datetime | None = None,
) -> tuple[str, datetime]:
    """
    Create a signed JWT access token.

    Returns:
        (encoded_token, expires_at) tuple.
    """
    expires_at = datetime.now(tz=UTC) + timedelta(
        minutes=_settings.jwt.access_token_expire_minutes
    )
    payload: dict[str, Any] = {
        "sub":       str(user_id),
        "role":      role,
        "agency_id": str(agency_id) if agency_id else None,
        "type":      TOKEN_TYPE_ACCESS,
        "exp":       expires_at,
        "iat":       datetime.now(tz=UTC),
        "jti":       str(uuid.uuid4()),   # unique token ID
        "sv":        session_version,
        "amr":       list(authentication_methods),
    }
    if mfa_authenticated_at is not None:
        payload["mfa_at"] = int(mfa_authenticated_at.timestamp())
    encoded = jwt.encode(
        payload,
        _settings.app_secret_key,
        algorithm=_settings.jwt.algorithm,
    )
    return encoded, expires_at


def create_refresh_token() -> tuple[str, datetime]:
    """
    Create an opaque refresh token (UUID).

    The token itself is stored in the database.
    Returns:
        (token_string, expires_at) tuple.
    """
    expires_at = datetime.now(tz=UTC) + timedelta(
        days=_settings.jwt.refresh_token_expire_days
    )
    return str(uuid.uuid4()), expires_at


def hash_refresh_token(token: str) -> str:
    """Hash refresh tokens before database storage or lookup."""
    return hmac.new(
        _settings.app_secret_key.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ── Token Verification ────────────────────────────────────────────────────────

def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and verify a JWT access token.

    Returns:
        The token payload dict.

    Raises:
        TokenExpiredError: If the token has expired.
        AuthenticationError: If the token is invalid.
    """
    try:
        payload = jwt.decode(
            token,
            _settings.app_secret_key,
            algorithms=[_settings.jwt.algorithm],
        )
    except ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except InvalidTokenError as exc:
        raise AuthenticationError("Invalid access token") from exc

    if payload.get("type") != TOKEN_TYPE_ACCESS:
        raise AuthenticationError("Invalid token type")

    return payload


def extract_user_id_from_token(token: str) -> uuid.UUID:
    """
    Convenience wrapper — decode token and return just the user_id.
    """
    payload = decode_access_token(token)
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid token subject") from exc
