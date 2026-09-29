"""Immutable mailbox ownership, including for platform superadministrators."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.domain.entities.entities import User, UserRole


class EmailScopeError(ValueError):
    pass


def email_agency_scope(user: User) -> uuid.UUID | None:
    if user.role == UserRole.SUPER_ADMIN:
        return None
    if user.agency_id is None:
        raise EmailScopeError("Your account is not assigned to the organization.")
    return user.agency_id


def email_owner_filters(owner_column: InstrumentedAttribute[uuid.UUID],
                        agency_column: InstrumentedAttribute[uuid.UUID],
                        user: User) -> tuple[ColumnElement[bool], ...]:
    filters = [owner_column == user.id]
    if user.role != UserRole.SUPER_ADMIN:
        filters.append(agency_column == email_agency_scope(user))
    return tuple(filters)
