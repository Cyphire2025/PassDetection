"""
Token Value Objects
===================
Immutable value objects representing authentication tokens.
Lives in the domain layer — no framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AccessToken:
    """Represents an issued JWT access token."""
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class RefreshTokenValue:
    """Represents an issued opaque refresh token."""
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class TokenPair:
    """A matched access + refresh token pair issued at login."""
    access: AccessToken
    refresh: RefreshTokenValue
