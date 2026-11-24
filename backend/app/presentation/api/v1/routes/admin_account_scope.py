"""Workforce account and group visibility predicates."""

from __future__ import annotations

from sqlalchemy.sql.elements import ColumnElement

from app.domain.entities.entities import (
    GroupStatus,
    User,
    UserRole,
)
from app.infrastructure.database.models import (
    UserModel,
)

REMOVED_GROUP_STATUSES = (GroupStatus.ARCHIVED.value, GroupStatus.DELETED.value)


def _manager_scope(current_user: User) -> list[ColumnElement[bool]]:
    if current_user.role == UserRole.SUPER_ADMIN:
        return [
            UserModel.role == UserRole.AGENCY_MANAGER.value,
            UserModel.deleted_at.is_(None),
        ]
    return [
        UserModel.role == UserRole.AGENCY_MANAGER.value,
        UserModel.agency_id == current_user.agency_id,
        UserModel.deleted_at.is_(None),
    ]


def _staff_scope(current_user: User) -> list[ColumnElement[bool]]:
    if current_user.role == UserRole.SUPER_ADMIN:
        return [
            UserModel.role == UserRole.AGENCY_STAFF.value,
            UserModel.deleted_at.is_(None),
        ]
    return [
        UserModel.role == UserRole.AGENCY_STAFF.value,
        UserModel.agency_id == current_user.agency_id,
        UserModel.deleted_at.is_(None),
    ]
