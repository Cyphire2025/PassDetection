"""Cookie transport for a signed superadmin access level."""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import jwt
from fastapi import Response

from app.core.config.settings import get_settings
from app.core.security.access_level import (  # noqa: F401
    ACCESS_LEVEL_COOKIE,
    access_level_response_values,
    apply_access_level,
    apply_access_level_cookie,
)
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthenticationError

__all__ = [
    "ACCESS_LEVEL_COOKIE", "access_level_response_values", "apply_access_level",
    "apply_access_level_cookie", "clear_access_level_cookie", "set_access_level_cookie",
]


def set_access_level_cookie(
    response: Response, *, user: User, role: UserRole, agency_id: uuid.UUID,
    agency_name: str, claims: Mapping[str, Any],
) -> None:
    settings = get_settings()
    now = datetime.now(tz=UTC)
    deadline = claims.get("session_exp", claims.get("exp"))
    if not isinstance(deadline, (int, float)) or deadline <= now.timestamp():
        raise AuthenticationError("The current sign-in has expired")
    token = jwt.encode(
        {
            "type": "dashboard_access_level", "sub": str(user.id),
            "sv": user.session_version, "role": role.value,
            "agency_id": str(agency_id), "agency_name": agency_name,
            "iat": int(now.timestamp()), "exp": int(deadline),
        },
        settings.app_secret_key, algorithm=settings.jwt.algorithm,
    )
    # Session cookie: closing the browser also ends the selected access level.
    response.set_cookie(
        ACCESS_LEVEL_COOKIE, token, httponly=True,
        secure=settings.jwt.cookie_secure or settings.is_production,
        samesite=settings.jwt.cookie_samesite, path="/",
    )


def clear_access_level_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        ACCESS_LEVEL_COOKIE, path="/", httponly=True,
        secure=settings.jwt.cookie_secure or settings.is_production,
        samesite=settings.jwt.cookie_samesite,
    )
