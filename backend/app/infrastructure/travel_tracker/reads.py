"""Paginated canonical tracker group/workspace reads with sensitive-read audit."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.travel_tracker import (
    TrackerGroupList,
    TrackerStatus,
    TrackerTrack,
    TrackerWorkspace,
)
from app.domain.entities.entities import User
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.repositories.sensitive_read_audit import record_sensitive_read
from app.infrastructure.travel_tracker.projections import counts, project_passenger
from app.infrastructure.travel_tracker.queries import (
    filter_roster,
    group_query,
    group_summary,
    load_group,
    roster,
    validate_filters,
    validate_page,
)


async def list_groups(
    session: AsyncSession,
    user: User,
    allowed_group_ids: Sequence[uuid.UUID] | None,
    *,
    search: str | None = None,
    page: int = 1,
    page_size: int = 24,
) -> TrackerGroupList:
    validate_page(page, page_size, 100)
    validate_filters("visa", "all", search)
    statement = group_query(user, allowed_group_ids)
    normalized = " ".join((search or "").split())
    if normalized:
        statement = statement.where(
            or_(
                ClientGroupModel.name.icontains(normalized, autoescape=True),
                ClientGroupModel.destination.icontains(normalized, autoescape=True),
            )
        )
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    groups = list(
        (
            await session.scalars(
                statement.order_by(ClientGroupModel.created_at.desc(), ClientGroupModel.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    summary = await group_summary(session, groups)
    return TrackerGroupList(
        groups=[summary[group.id] for group in groups], total=total, page=page, page_size=page_size
    )


async def workspace(
    session: AsyncSession,
    user: User,
    allowed_group_ids: Sequence[uuid.UUID] | None,
    group_id: uuid.UUID,
    *,
    track: TrackerTrack = "visa",
    status: TrackerStatus = "all",
    search: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> TrackerWorkspace:
    validate_page(page, page_size)
    group = await load_group(session, user, allowed_group_ids, group_id)
    statement = filter_roster(roster(group), track=track, status=status, search=search)
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = (
        await session.execute(
            statement.order_by(
                func.lower(PassportSubmissionModel.client_name), PassportSubmissionModel.id
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    summary = (await group_summary(session, [group]))[group.id]
    await record_sensitive_read(
        session,
        user=user,
        kind="group_view",
        agency_id=group.agency_id,
        entity_id=group.id,
        count=len(rows),
    )
    return TrackerWorkspace(
        group=summary,
        counts=counts(summary, track),
        passengers=[project_passenger(passenger, tracker) for passenger, tracker in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
