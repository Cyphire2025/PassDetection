"""Apply the selected office role's tenant scope to document workflows."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.domain.entities.entities import User, UserRole


def document_scope_available(user: User) -> bool:
    return user.role == UserRole.SUPER_ADMIN or (
        user.agency_id is not None
        and user.role in {UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF}
    )


def document_agency_scope(
    column: InstrumentedAttribute[uuid.UUID], user: User,
) -> list[ColumnElement[bool]]:
    return [] if user.role == UserRole.SUPER_ADMIN else [column == user.agency_id]
