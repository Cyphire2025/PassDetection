"""Tenant scope, revision fences and audit policy shared by menu transports."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.use_cases.menu.meal_plan_generator import PlannerCategory
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.menu_models import MealPlanModel, MenuCategoryModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.security.client_ip import trusted_client_ip

MENU_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
]


def _agency_scope(current_user: User) -> uuid.UUID | None:
    if current_user.agency_id is None and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not assigned to an agency",
        )
    return current_user.agency_id


def _category_scope(
    model: type[MenuCategoryModel],
    agency_id: uuid.UUID | None,
) -> ColumnElement[bool]:
    if agency_id is None:
        return model.agency_id.is_(None)
    return model.agency_id == agency_id


def _plan_scope(
    model: type[MealPlanModel],
    agency_id: uuid.UUID | None,
) -> ColumnElement[bool]:
    if agency_id is None:
        return model.agency_id.is_(None)
    return model.agency_id == agency_id


def _require_current_revision(
    *,
    actual: datetime,
    expected: datetime,
    resource: str,
) -> None:
    actual_utc = _normalized_revision(actual)
    expected_utc = _normalized_revision(expected)
    if actual_utc == expected_utc:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "MENU_REVISION_CONFLICT",
            "message": (
                f"This {resource} changed in another session. "
                "Refresh the menu workspace and retry your change."
            ),
            "current_updated_at": actual_utc.isoformat(),
        },
    )


def _require_current_category_revisions(
    categories: list[PlannerCategory],
    expected: Mapping[uuid.UUID, datetime],
) -> None:
    current_ids = {category.id for category in categories}
    if set(expected) != current_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MENU_REVISION_CONFLICT",
                "message": (
                    "The menu category selection changed in another session. "
                    "Refresh the menu workspace and regenerate the plan."
                ),
                "current_category_ids": sorted(str(item) for item in current_ids),
            },
        )
    for category in categories:
        if category.updated_at is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "MENU_REVISION_CONFLICT",
                    "message": "The menu category revision is unavailable.",
                },
            )
        _require_current_revision(
            actual=category.updated_at,
            expected=expected[category.id],
            resource="menu category",
        )


def _normalized_revision(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalized_name(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def _excel_filename(plan_name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", plan_name).strip("-").lower()
    return f"{(normalized[:80] or 'meal-plan')}.xlsx"


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


async def _audit(
    session: AsyncSession,
    current_user: User,
    request: Request,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    metadata: Mapping[str, object],
) -> None:
    await AuditLogRepository(session).record(
        action=action,
        entity_type=entity_type,
        agency_id=current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(entity_id),
        ip_address=trusted_client_ip(request),
        metadata=dict(metadata),
    )
