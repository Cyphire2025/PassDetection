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

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.jwt import decode_access_token
from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthenticationError, AuthorizationError
from app.domain.repositories.interfaces import IUserRepository
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.user_repository import UserRepository

_bearer = HTTPBearer(auto_error=False)


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
    token = credentials.credentials if credentials else request.cookies.get(get_settings().jwt.access_cookie_name)
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

def require_role(allowed_roles: list[UserRole]):
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
