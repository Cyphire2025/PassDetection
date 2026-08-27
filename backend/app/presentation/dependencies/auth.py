"""
FastAPI Auth Dependencies
=========================
Reusable dependencies injected into route handlers.

Pattern:
  - get_current_user      → any authenticated user
  - get_current_active_user → authenticated + active
  - require_role(roles)   → role-gated dependency factory

Usage in routes:
    @router.get("/me")
    async def get_me(user: User = Depends(get_current_active_user)):
        ...

    @router.delete("/agency/{id}")
    async def delete_agency(
        user: User = Depends(require_role([UserRole.SUPER_ADMIN]))
    ):
        ...
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.core.security.jwt import decode_access_token
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import (
    AuthenticationError,
    AuthorizationError,
    StepUpRequiredError,
)
from app.domain.repositories.interfaces import IUserRepository
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.identity_security_repository import role_requires_dashboard_mfa
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.dependencies.csrf import require_cookie_csrf

_bearer = HTTPBearer(auto_error=False)

# WhatsApp broadcasts expose recipient lists and outbound messaging controls.
# Keep the capability allowlist centralized so the main broadcast routes and
# group-link integration cannot drift apart.
WHATSAPP_BROADCAST_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
]


# ── Repository Dependency ─────────────────────────────────────────────────────

def get_user_repository(
    session: AsyncSession = Depends(get_db_session),
) -> IUserRepository:
    """Provide a UserRepository bound to the current request's DB session."""
    return UserRepository(session)


# ── Token Extraction ──────────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    user_repo: IUserRepository = Depends(get_user_repository),
) -> User:
    """
    Decode the Bearer token and return the corresponding User entity.

    Raises:
        AuthenticationError: If token is missing, invalid, or user not found.
    """
    if credentials is None and request.method.upper() not in {
        "GET",
        "HEAD",
        "OPTIONS",
        "TRACE",
    }:
        await require_cookie_csrf(request)

    token = (
        credentials.credentials
        if credentials
        else request.cookies.get(get_settings().jwt.access_cookie_name)
    )
    if not token:
        raise AuthenticationError("Authorization header missing")

    payload = decode_access_token(token)

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid token payload") from exc

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise AuthenticationError("User not found")
    if user.role == UserRole.CLIENT_MANAGER:
        raise AuthenticationError("This account cannot access the dashboard")
    user_session_version = getattr(user, "session_version", None)
    if user_session_version is not None and payload.get("sv") != user_session_version:
        raise AuthenticationError("Session is no longer valid")
    if getattr(user, "credential_state", "active") != "active":
        raise AuthenticationError("Credential setup is required")
    if hasattr(request, "state"):
        request.state.auth_claims = payload

    return user


async def get_current_active_user(
    user: User = Depends(get_current_user),
) -> User:
    """
    Extends get_current_user — also checks the account is active.

    Raises:
        AuthenticationError: If account is deactivated.
    """
    if not user.is_active:
        raise AuthenticationError("Your account has been deactivated")
    return user


# ── Role-Based Access Control ────────────────────────────────────────────────

def require_role(
    allowed_roles: list[UserRole],
) -> Callable[[User], Awaitable[User]]:
    """
    Dependency factory for role-gated endpoints.

    Usage:
        Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN]))
    """
    async def _check_role(user: User = Depends(get_current_active_user)) -> User:
        if user.role not in allowed_roles:
            raise AuthorizationError(
                f"This action requires one of: {[r.value for r in allowed_roles]}"
            )
        return user

    return _check_role


async def require_recent_mfa(
    request: Request,
    user: User = Depends(get_current_active_user),
) -> User:
    """Require MFA performed in the last ten minutes for privileged users."""

    if not role_requires_dashboard_mfa(user.role):
        return user
    payload = getattr(getattr(request, "state", None), "auth_claims", {})
    methods = payload.get("amr") if isinstance(payload, dict) else None
    raw_mfa_at = payload.get("mfa_at") if isinstance(payload, dict) else None
    if (
        not isinstance(methods, list)
        or not any(method in {"totp", "recovery_code"} for method in methods)
        or not isinstance(raw_mfa_at, (int, float))
    ):
        raise StepUpRequiredError()
    age_seconds = datetime.now(tz=UTC).timestamp() - float(raw_mfa_at)
    if age_seconds < -60 or age_seconds > 600:
        raise StepUpRequiredError()
    return user
