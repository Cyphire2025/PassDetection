"""Client-manager persistence error and response normalization support."""

from __future__ import annotations

from typing import Literal

from sqlalchemy.exc import IntegrityError

from app.infrastructure.database.gc_mobile_models import (
    ClientManagerProfileModel,
    ClientOrganizationModel,
)
from app.infrastructure.database.models import UserModel
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerAssignedGroupResponse,
    ClientManagerResponse,
    ClientOrganizationResponse,
)

_CLIENT_MANAGER_DUPLICATE_CONSTRAINT_MESSAGES = {
    "users_email_key": "Email is already in use",
    "uq_client_manager_phone_live": ("Mobile number is already assigned to another Client Manager"),
}


def integrity_constraint_name(exc: IntegrityError) -> str | None:
    """Extract a database constraint name without relying on driver internals."""

    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        constraint_name = getattr(current, "constraint_name", None)
        if isinstance(constraint_name, str) and constraint_name:
            return constraint_name
        diagnostic = getattr(current, "diag", None)
        diagnostic_name = getattr(diagnostic, "constraint_name", None)
        if isinstance(diagnostic_name, str) and diagnostic_name:
            return diagnostic_name
        for linked in (
            getattr(current, "orig", None),
            current.__cause__,
            current.__context__,
        ):
            if isinstance(linked, BaseException):
                pending.append(linked)

    message = str(exc)
    for known_name in _CLIENT_MANAGER_DUPLICATE_CONSTRAINT_MESSAGES:
        if known_name in message:
            return known_name
    return None


def client_manager_duplicate_message(exc: IntegrityError) -> str | None:
    constraint_name = integrity_constraint_name(exc)
    if constraint_name is None:
        return None
    return _CLIENT_MANAGER_DUPLICATE_CONSTRAINT_MESSAGES.get(constraint_name)


def organization_status(value: str) -> Literal["active", "inactive"]:
    if value == "active":
        return "active"
    if value == "inactive":
        return "inactive"
    raise ValueError("Unsupported client organization status")


def client_manager_status(
    value: str,
) -> Literal["active", "suspended", "deleted", "invited"]:
    if value == "active":
        return "active"
    if value == "suspended":
        return "suspended"
    if value == "deleted":
        return "deleted"
    if value == "invited":
        return "invited"
    raise ValueError("Unsupported client manager status")


def organization_response(item: ClientOrganizationModel) -> ClientOrganizationResponse:
    return ClientOrganizationResponse(
        id=item.id,
        agency_id=item.agency_id,
        name=item.name,
        status=organization_status(item.status),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def client_manager_response(
    profile: ClientManagerProfileModel,
    user: UserModel,
    organization: ClientOrganizationModel,
    assigned_groups: list[ClientManagerAssignedGroupResponse],
) -> ClientManagerResponse:
    return ClientManagerResponse(
        id=profile.id,
        user_id=user.id,
        agency_id=profile.agency_id,
        full_name=user.full_name,
        email=user.email,
        phone_number=profile.normalized_phone_number,
        organization_id=organization.id,
        organization_name=organization.name,
        status=client_manager_status(profile.status),
        force_password_change=profile.force_password_change,
        revision=profile.revision,
        group_ids=[group.id for group in assigned_groups],
        assigned_groups=assigned_groups,
        last_login_at=user.last_login_at,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )
