"""
Global Search Routes
====================
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    User,
    UserRole,
)
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.schemas.search_schemas import GlobalSearchResult
from app.presentation.dependencies.auth import get_current_active_user

router = APIRouter()


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
    return passport_results + group_results


async def _search_passports(
    session: AsyncSession,
    current_user: User,
    query: str,
    limit: int,
) -> list[GlobalSearchResult]:
    pattern = f"%{query}%"
    stmt = (
        select(
            PassportSubmissionModel,
            ClientGroupModel.name.label("group_name"),
            ClientGroupModel.destination.label("destination"),
        )
        .join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        .where(PassportSubmissionModel.status.in_(_submitted_statuses()))
        .where(
            or_(
                func.lower(PassportSubmissionModel.client_name).like(pattern),
                func.lower(PassportSubmissionModel.client_email).like(pattern),
                func.lower(PassportSubmissionModel.client_phone).like(pattern),
                func.lower(PassportSubmissionModel.departure_city).like(pattern),
                func.lower(ClientGroupModel.name).like(pattern),
                func.lower(ClientGroupModel.destination).like(pattern),
                func.lower(PassportSubmissionModel.extracted_fields["passport_number"].astext).like(pattern),
                func.lower(PassportSubmissionModel.confirmed_fields["passport_number"].astext).like(pattern),
                func.lower(PassportSubmissionModel.extracted_fields["surname"].astext).like(pattern),
                func.lower(PassportSubmissionModel.confirmed_fields["surname"].astext).like(pattern),
                func.lower(PassportSubmissionModel.extracted_fields["given_names"].astext).like(pattern),
                func.lower(PassportSubmissionModel.confirmed_fields["given_names"].astext).like(pattern),
            )
        )
        .order_by(PassportSubmissionModel.updated_at.desc())
        .limit(limit)
    )
    stmt = _apply_visibility_scope(stmt, current_user)
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
    pattern = f"%{query}%"
    stmt = (
        select(ClientGroupModel)
        .where(
            or_(
                func.lower(ClientGroupModel.name).like(pattern),
                func.lower(ClientGroupModel.destination).like(pattern),
            )
        )
        .order_by(ClientGroupModel.created_at.desc())
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


def _apply_visibility_scope(stmt, current_user: User):  # type: ignore[no-untyped-def]
    return AuthorizationPolicy.apply_passport_visibility_scope(stmt, current_user)


def _apply_group_visibility_scope(stmt, current_user: User):  # type: ignore[no-untyped-def]
    return AuthorizationPolicy.apply_group_visibility_scope(stmt, current_user)


def _submitted_statuses() -> tuple[str, ...]:
    return OFFICE_VISIBLE_PASSPORT_STATUS_VALUES


def _string_field(fields: dict, key: str) -> str | None:
    value = fields.get(key)
    return str(value).strip() if value else None
