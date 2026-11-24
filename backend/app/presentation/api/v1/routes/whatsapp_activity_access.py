"""Role admission and shared client-group visibility for activity queries."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User, UserRole
from app.presentation.api.v1.schemas.whatsapp_activity_schemas import WhatsAppActivityKind
from app.presentation.dependencies.auth import WHATSAPP_BROADCAST_ROLES

ACTIVITY_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
]


def _scope_client_group_statement(statement: Any, current_user: User) -> Any:
    return AuthorizationPolicy.apply_group_visibility_scope(statement, current_user)


def _ensure_kind_access(kind: WhatsAppActivityKind, current_user: User) -> None:
    if kind == "broadcast" and current_user.role not in WHATSAPP_BROADCAST_ROLES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast activity not found",
        )
