"""Authentication inputs and public account/session results."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.entities import User


@dataclass(frozen=True)
class LoginInputDTO:
    """Input for LoginUseCase."""

    email: str
    password: str


@dataclass(frozen=True)
class RefreshTokenInputDTO:
    """Input for RefreshTokenUseCase."""

    refresh_token: str


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
    credential_state: str = "active"
    mfa_required: bool = False
    mfa_enabled: bool = False


def user_output_from_entity(user: User) -> UserOutputDTO:
    """Project the same public account fields for login, refresh and profile reads."""
    return UserOutputDTO(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        agency_id=user.agency_id,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
        credential_state=user.credential_state,
        mfa_required=user.mfa_required,
        mfa_enabled=user.mfa_enabled,
    )


@dataclass(frozen=True)
class AuthResponseDTO:
    """Returned by LoginUseCase and RefreshTokenUseCase."""

    user: UserOutputDTO
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_token_expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
