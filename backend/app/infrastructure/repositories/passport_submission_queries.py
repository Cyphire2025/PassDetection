"""Shared tenant, staff, coordinator, lifecycle and search query boundaries."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, or_, select

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import (
    CONFIRMED_PASSPORT_STATUS_VALUES,
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    PENDING_REVIEW_PASSPORT_STATUS_VALUES,
    PassportProcessingStatus,
    User,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    ManagerGroupAccessModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.search_expressions import (
    passport_search_fields,
    substring_predicate,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member


def _office_visible_statuses() -> tuple[str, ...]:
    return OFFICE_VISIBLE_PASSPORT_STATUS_VALUES


def _status_filter_values(status_filter: str) -> tuple[str, ...]:
    if status_filter == PassportProcessingStatus.CONFIRMED.value:
        return CONFIRMED_PASSPORT_STATUS_VALUES
    if status_filter == PassportProcessingStatus.REVIEW_REQUIRED.value:
        return PENDING_REVIEW_PASSPORT_STATUS_VALUES
    if status_filter == PassportProcessingStatus.CLIENT_SUBMITTED.value:
        return OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
    return (status_filter,)


def _apply_manager_group_scope(stmt, manager_id: uuid.UUID):  # type: ignore[no-untyped-def]
    return stmt.outerjoin(
        ManagerGroupAccessModel,
        (ManagerGroupAccessModel.group_id == ClientGroupModel.id)
        & (ManagerGroupAccessModel.manager_id == manager_id),
    ).where(
        or_(
            ClientGroupModel.created_by_user_id == manager_id,
            ManagerGroupAccessModel.manager_id == manager_id,
        )
    )


def _agency_scope(
    stmt: Any,
    agency_id: uuid.UUID,
    *,
    status_filter: str | None,
    exclude_archived_groups: bool,
    created_by_user_id: uuid.UUID | None,
    visible_to_user: User | None,
) -> Any:
    """One canonical scope for full lists, counts and the bounded preview."""
    stmt = stmt.where(
        PassportSubmissionModel.agency_id == agency_id,
        PassportSubmissionModel.status.in_(_office_visible_statuses()),
    )
    if exclude_archived_groups or created_by_user_id or visible_to_user:
        stmt = stmt.join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
    if exclude_archived_groups:
        stmt = stmt.where(ClientGroupModel.status.notin_(["archived", "deleted"]))
    if created_by_user_id:
        stmt = _apply_manager_group_scope(stmt, created_by_user_id)
    if visible_to_user:
        stmt = AuthorizationPolicy.apply_passport_visibility_scope(stmt, visible_to_user)
    if status_filter:
        stmt = stmt.where(PassportSubmissionModel.status.in_(_status_filter_values(status_filter)))
    return stmt


def _group_scope(
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    exclude_archived_groups: bool = False,
    created_by_user_id: uuid.UUID | None = None,
    visible_to_user: User | None = None,
    operational_only: bool = False,
) -> Select[tuple[PassportSubmissionModel]]:
    stmt = (
        select(PassportSubmissionModel)
        .join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(_office_visible_statuses()),
        )
    )
    if operational_only:
        stmt = stmt.where(operational_roster_member())
    if exclude_archived_groups:
        stmt = stmt.where(ClientGroupModel.status.notin_(["archived", "deleted"]))
    if created_by_user_id:
        stmt = _apply_manager_group_scope(stmt, created_by_user_id)
    if visible_to_user:
        stmt = AuthorizationPolicy.apply_passport_visibility_scope(stmt, visible_to_user)
    return stmt


def _apply_search(stmt, search: str | None):  # type: ignore[no-untyped-def]
    if not search or not search.strip():
        return stmt
    return stmt.where(
        substring_predicate(
            search.strip(),
            fields=passport_search_fields(include_given_names=False),
            indexed_fields=passport_search_fields(),
        )
    )
