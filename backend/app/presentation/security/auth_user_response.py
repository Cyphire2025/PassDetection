"""Consistent effective role and true account identity in auth responses."""

from __future__ import annotations

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.schemas.auth_schemas import UserResponse


def user_response(user: object) -> UserResponse:
    values = dict(vars(user))
    raw_role = values.get("role")
    role = raw_role.value if isinstance(raw_role, UserRole) else raw_role
    actual_role = values.get("actual_role") or role
    if isinstance(actual_role, UserRole):
        actual_role = actual_role.value
    active = values.get("is_active") is True
    can_manage_gc_app = active and (
        role == UserRole.SUPER_ADMIN.value
        or (role in {UserRole.AGENCY_ADMIN.value, UserRole.AGENCY_MANAGER.value}
            and values.get("agency_id") is not None)
    )
    values.update(
        role=role, actual_role=actual_role, access_level=role,
        can_switch_access_level=active and actual_role == UserRole.SUPER_ADMIN.value,
        capabilities=["gc_app.manage"] if can_manage_gc_app else [],
    )
    return UserResponse.model_validate(values)
