"""Signed, session-bound access reduction for an existing superadmin identity."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import jwt

from app.application.security.access_level_actor import actual_user_agency_id, actual_user_role
from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthenticationError

ACCESS_LEVEL_COOKIE = "dashboard_access_level"
ACCESS_LEVEL_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
    UserRole.AGENCY_COORDINATOR,
}


def apply_access_level(
    user: User, *, role: UserRole, agency_id: uuid.UUID, agency_name: str | None
) -> User:
    """Return an effective principal without changing the persisted account."""
    if actual_user_role(user) != UserRole.SUPER_ADMIN or not user.is_active:
        raise AuthenticationError("Access-level switching is unavailable for this account")
    if role not in ACCESS_LEVEL_ROLES or role == UserRole.SUPER_ADMIN:
        raise AuthenticationError("Invalid access level")
    return replace(
        user, role=role, agency_id=agency_id,
        actual_role=UserRole.SUPER_ADMIN,
        actual_agency_id=actual_user_agency_id(user),
        access_level_agency_name=agency_name,
    )


def _mode_values(
    values: dict[str, Any], cookies: Mapping[str, str], claims: Mapping[str, Any]
) -> dict[str, Any]:
    token = cookies.get(ACCESS_LEVEL_COOKIE)
    if not token:
        return values
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.app_secret_key, algorithms=[settings.jwt.algorithm],
            options={"require": ["exp", "iat", "sub", "sv", "type", "role", "agency_id"]},
        )
        role = UserRole(payload["role"])
        agency_id = uuid.UUID(payload["agency_id"])
        deadline = claims.get("session_exp", claims.get("exp"))
        if (
            payload["type"] != "dashboard_access_level"
            or values.get("role") != UserRole.SUPER_ADMIN
            or not values.get("is_active")
            or payload["sub"] != str(values["id"])
            or payload["sv"] != claims.get("sv")
            or (values.get("session_version") is not None
                and payload["sv"] != values["session_version"])
            or not isinstance(deadline, (int, float))
            or payload["exp"] > deadline
            or role not in ACCESS_LEVEL_ROLES
            or role == UserRole.SUPER_ADMIN
        ):
            raise ValueError("Access-level context mismatch")
    except (jwt.InvalidTokenError, ValueError, KeyError, TypeError) as exc:
        raise AuthenticationError("Access level expired or is invalid; restore Super Admin") from exc
    return {
        **values,
        "role": role,
        "agency_id": agency_id,
        "actual_role": UserRole.SUPER_ADMIN,
        "actual_agency_id": values.get("agency_id"),
        "access_level_agency_name": payload.get("agency_name"),
    }


def apply_access_level_cookie(
    user: User, cookies: Mapping[str, str], claims: Mapping[str, Any]
) -> User:
    if not cookies.get(ACCESS_LEVEL_COOKIE):
        return user
    values = _mode_values(dict(vars(user)), cookies, claims)
    return replace(user, **values)


def access_level_response_values(
    user: object, cookies: Mapping[str, str], claims: Mapping[str, Any]
) -> dict[str, Any]:
    return _mode_values(dict(vars(user)), cookies, claims)
