"""
Auth Application DTOs
=====================
Data Transfer Objects for auth use cases.

DTOs are the input/output contracts of use cases.
They are NOT domain entities and NOT HTTP schemas.
They carry only the data each use case needs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


# ── Input DTOs (Use Case arguments) ──────────────────────────────────────────

@dataclass(frozen=True)
class LoginInputDTO:
    """Input for LoginUseCase."""
    email: str
    password: str


@dataclass(frozen=True)
class RefreshTokenInputDTO:
    """Input for RefreshTokenUseCase."""
    refresh_token: str


# ── Output DTOs (Use Case return values) ──────────────────────────────────────

@dataclass(frozen=True)
class UserOutputDTO:
    """Represents a user as returned to the presentation layer."""
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    agency_id: uuid.UUID | None
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AuthResponseDTO:
    """Returned by LoginUseCase and RefreshTokenUseCase."""
    user: UserOutputDTO
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_token_expires_at: datetime | None = None
