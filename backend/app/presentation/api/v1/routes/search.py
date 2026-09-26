"""
Global Search Routes
====================
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar, cast

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only
from sqlalchemy.sql import Select

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    User,
    UserRole,
)
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.search_expressions import (
    group_search_fields,
    passport_search_fields,
    substring_predicate,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.sensitive_read_audit import record_sensitive_read
from app.presentation.api.v1.schemas.search_schemas import GlobalSearchResult
from app.presentation.dependencies.auth import get_current_active_user

router = APIRouter()
_SearchRow = TypeVar("_SearchRow", bound=tuple[object, ...])


@router.get(
    "",
    response_model=list[GlobalSearchResult],
    status_code=status.HTTP_200_OK,
    summary="Search passports and groups visible to the current user",
)
async def global_search(
    q: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(12, ge=1, le=30),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[GlobalSearchResult]:
    if current_user.role != UserRole.SUPER_ADMIN and not current_user.agency_id:
        return []

    query = q.strip().lower()
    if len(query) < 2:
        return []

    passport_results = await _search_passports(session, current_user, query, limit)
    remaining = max(0, limit - len(passport_results))
    group_results = await _search_groups(session, current_user, query, remaining)
    await record_sensitive_read(session, user=current_user, kind="search",
                                agency_id=current_user.agency_id, count=len(passport_results))
    return passport_results + group_results


def passport_search_statement(current_user: User, query: str, limit: int) -> Select[tuple[PassportSubmissionModel, str, str | None]]:
    """Use separate indexed candidates for passport and group-name matches.

    A joined OR forces PostgreSQL to inspect wide rows from both tables. Each
    UNION branch now uses its own trigram predicate, then tenant/owner/lifecycle
    authorization is applied again before returning any passenger data.
    """
    base = (select(PassportSubmissionModel.id)
            .join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
            .where(PassportSubmissionModel.status.in_(_submitted_statuses())))
    own = _apply_visibility_scope(base.where(substring_predicate(query, fields=passport_search_fields())), current_user)
    groups = _apply_visibility_scope(base.where(substring_predicate(query, fields=group_search_fields())), current_user)
    stmt = (
        select(PassportSubmissionModel, ClientGroupModel.name.label("group_name"),
               ClientGroupModel.destination.label("destination"))
        .options(load_only(PassportSubmissionModel.id, PassportSubmissionModel.group_id,
                           PassportSubmissionModel.client_name, PassportSubmissionModel.client_email,
                           PassportSubmissionModel.client_phone, PassportSubmissionModel.status,
                           PassportSubmissionModel.updated_at, PassportSubmissionModel.confirmed_fields,
                           PassportSubmissionModel.extracted_fields))
        .join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        .where(PassportSubmissionModel.id.in_(own.union(groups)))
        .order_by(PassportSubmissionModel.updated_at.desc(), PassportSubmissionModel.id.desc())
        .limit(limit)
    )
    return _apply_visibility_scope(stmt, current_user)


async def _search_passports(
    session: AsyncSession,
    current_user: User,
    query: str,
    limit: int,
) -> list[GlobalSearchResult]:
    stmt = passport_search_statement(current_user, query, limit)
    result = await session.execute(stmt)
    rows = result.all()

    search_results: list[GlobalSearchResult] = []
    for submission, group_name, destination in rows:
        fields = submission.confirmed_fields or submission.extracted_fields or {}
        passport_number = _string_field(fields, "passport_number")
        title = passport_number or submission.client_name
        subtitle_parts = [submission.client_name, group_name]
        if submission.client_email:
            subtitle_parts.append(submission.client_email)
        search_results.append(
            GlobalSearchResult(
                type="passport",
                id=submission.id,
                group_id=submission.group_id,
                title=title,
                subtitle=" | ".join(part for part in subtitle_parts if part),
                status=submission.status,
                passport_number=passport_number,
                client_name=submission.client_name,
                client_email=submission.client_email,
                client_phone=submission.client_phone,
                group_name=group_name,
                destination=destination,
                updated_at=submission.updated_at,
            )
        )
    return search_results


async def _search_groups(
    session: AsyncSession,
    current_user: User,
    query: str,
    limit: int,
) -> list[GlobalSearchResult]:
    if limit <= 0:
        return []
    stmt = (
        select(ClientGroupModel)
        .where(substring_predicate(query, fields=group_search_fields()))
        .order_by(ClientGroupModel.created_at.desc(), ClientGroupModel.id.desc())
        .limit(limit)
    )
    stmt = _apply_group_visibility_scope(stmt, current_user)
    result = await session.execute(stmt)
    return [
        GlobalSearchResult(
            type="group",
            id=group.id,
            group_id=group.id,
            title=group.name,
            subtitle=f"{group.status.capitalize()} group",
            status=group.status,
            group_name=group.name,
            destination=group.destination,
            updated_at=group.closed_at or group.created_at,
        )
        for group in result.scalars().all()
    ]


def _apply_visibility_scope(
    stmt: Select[_SearchRow], current_user: User
) -> Select[_SearchRow]:
    return cast(
        Select[_SearchRow],
        AuthorizationPolicy.apply_passport_visibility_scope(stmt, current_user),
    )


def _apply_group_visibility_scope(
    stmt: Select[_SearchRow], current_user: User
) -> Select[_SearchRow]:
    return cast(
        Select[_SearchRow],
        AuthorizationPolicy.apply_group_visibility_scope(stmt, current_user),
    )


def _submitted_statuses() -> tuple[str, ...]:
    return OFFICE_VISIBLE_PASSPORT_STATUS_VALUES


def _string_field(fields: Mapping[str, object], key: str) -> str | None:
    value = fields.get(key)
    return str(value).strip() if value else None
