"""Keep passport-group data within staff's existing ownership/assignment scope."""

from __future__ import annotations

from sqlalchemy.sql.elements import ColumnElement

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import GroupStatus, User, UserRole
from app.infrastructure.database.models import ClientGroupModel


def staff_linked_group_filters(current_user: User) -> list[ColumnElement[bool]]:
    """Broadcast access does not grant access to unrelated passport groups."""

    if current_user.role != UserRole.AGENCY_STAFF:
        return []
    return [
        ClientGroupModel.agency_id == current_user.agency_id,
        AuthorizationPolicy.staff_group_visibility_filter(current_user),
        ClientGroupModel.status.not_in([GroupStatus.ARCHIVED.value, GroupStatus.DELETED.value]),
    ]
