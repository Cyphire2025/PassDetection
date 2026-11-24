"""Submission lookups, paginated reads and bounded dashboard projections."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import (
    GroupStatus,
    PassportProcessingStatus,
    PassportSubmission,
    User,
)
from app.domain.value_objects.dashboard_summary import (
    RECENT_DASHBOARD_LIMIT,
    RECENT_DASHBOARD_TEXT_LIMIT,
    DashboardProjectionLimitError,
    DashboardRecentSubmission,
)
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.repositories.passport_submission_mapping import _to_entity
from app.infrastructure.repositories.passport_submission_queries import (
    _agency_scope,
    _apply_search,
    _group_scope,
)


async def get_by_id(session: AsyncSession, submission_id: uuid.UUID) -> PassportSubmission | None:
    result = await session.execute(
        select(PassportSubmissionModel).where(PassportSubmissionModel.id == submission_id)
    )
    model = result.scalar_one_or_none()
    return _to_entity(model) if model else None


async def get_by_upload_idempotency_key(
    session: AsyncSession, group_id: uuid.UUID, upload_idempotency_key: str
) -> PassportSubmission | None:
    result = await session.execute(
        select(PassportSubmissionModel).where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.upload_idempotency_key == upload_idempotency_key,
        )
    )
    model = result.scalar_one_or_none()
    return _to_entity(model) if model else None


async def get_by_id_for_update(
    session: AsyncSession, submission_id: uuid.UUID
) -> PassportSubmission | None:
    """Lock one submission until the caller commits or rolls back."""

    result = await session.execute(
        select(PassportSubmissionModel)
        .where(PassportSubmissionModel.id == submission_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    model = result.scalar_one_or_none()
    return _to_entity(model) if model else None


async def list_by_agency(
    session: AsyncSession,
    agency_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 50,
    status_filter: str | None = None,
    search: str | None = None,
    exclude_archived_groups: bool = False,
    created_by_user_id: uuid.UUID | None = None,
    visible_to_user: User | None = None,
) -> list[PassportSubmission]:
    stmt = _agency_scope(
        select(PassportSubmissionModel),
        agency_id,
        status_filter=status_filter,
        exclude_archived_groups=exclude_archived_groups,
        created_by_user_id=created_by_user_id,
        visible_to_user=visible_to_user,
    )
    stmt = _apply_search(stmt, search)
    stmt = (
        stmt.order_by(PassportSubmissionModel.created_at.desc(), PassportSubmissionModel.id.desc())
        .offset(skip)
        .limit(limit)
    )

    result = await session.execute(stmt)
    return [_to_entity(m) for m in result.scalars().all()]


async def list_recent_dashboard_submissions(
    session: AsyncSession,
    agency_id: uuid.UUID,
    *,
    created_by_user_id: uuid.UUID | None = None,
    visible_to_user: User | None = None,
) -> list[DashboardRecentSubmission]:
    model = PassportSubmissionModel
    # The extra character detects invalid retained data without loading an
    # unbounded value. No JSON, document key or other ORM column is selected.
    bound = RECENT_DASHBOARD_TEXT_LIMIT + 1
    stmt = (
        _agency_scope(
            select(
                model.id,
                func.substr(model.client_name, 1, bound).label("client_name"),
                func.substr(model.client_email, 1, bound).label("client_email"),
                model.status,
                model.created_at,
                model.overall_confidence,
            ),
            agency_id,
            status_filter=PassportProcessingStatus.CLIENT_SUBMITTED.value,
            exclude_archived_groups=True,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )
        .order_by(model.created_at.desc(), model.id.desc())
        .limit(RECENT_DASHBOARD_LIMIT)
    )
    rows = (await session.execute(stmt)).mappings().all()
    if any(
        len(row["client_name"]) > RECENT_DASHBOARD_TEXT_LIMIT
        or len(row["client_email"] or "") > RECENT_DASHBOARD_TEXT_LIMIT
        for row in rows
    ):
        raise DashboardProjectionLimitError("Dashboard preview exceeds its field bounds")
    return [
        DashboardRecentSubmission(**{**row, "status": PassportProcessingStatus(row["status"])})
        for row in rows
    ]


async def list_by_group(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int | None = 50,
    search: str | None = None,
    exclude_archived_groups: bool = False,
    created_by_user_id: uuid.UUID | None = None,
    visible_to_user: User | None = None,
    operational_only: bool = False,
) -> list[PassportSubmission]:
    stmt = _group_scope(
        agency_id,
        group_id,
        exclude_archived_groups=exclude_archived_groups,
        created_by_user_id=created_by_user_id,
        visible_to_user=visible_to_user,
        operational_only=operational_only,
    )
    stmt = _apply_search(stmt, search)
    stmt = stmt.order_by(
        PassportSubmissionModel.created_at.desc(), PassportSubmissionModel.id.desc()
    )
    if skip:
        stmt = stmt.offset(skip)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return [_to_entity(m) for m in result.scalars().all()]


async def count_by_agency(
    session: AsyncSession,
    agency_id: uuid.UUID,
    *,
    status_filter: str | None = None,
    exclude_archived_groups: bool = False,
    created_by_user_id: uuid.UUID | None = None,
    visible_to_user: User | None = None,
) -> int:
    stmt = _agency_scope(
        select(func.count()).select_from(PassportSubmissionModel),
        agency_id,
        status_filter=status_filter,
        exclude_archived_groups=exclude_archived_groups,
        created_by_user_id=created_by_user_id,
        visible_to_user=visible_to_user,
    )
    # Dashboard totals cover the live/closed and archived Group Links lists,
    # including for superadmins who can otherwise access retained deleted data.
    stmt = stmt.where(
        PassportSubmissionModel.group_id.in_(
            select(ClientGroupModel.id)
            .where(
                ClientGroupModel.agency_id == agency_id,
                ClientGroupModel.status.in_(
                    [GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value, GroupStatus.ARCHIVED.value]
                ),
                ClientGroupModel.deleted_at.is_(None),
            )
            .correlate(None)
        )
    )

    result = await session.execute(stmt)
    return int(result.scalar_one())
