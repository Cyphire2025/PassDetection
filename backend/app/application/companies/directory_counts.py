"""Submission counts and chronology restricted to groups the reader can view."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import visible_company_groups
from app.domain.entities.entities import User
from app.infrastructure.database.company_directory_models import (
    CompanyDirectoryGroupCountModel as Count,
)


async def visible_submission_counts(session: AsyncSession, user: User, agency_id: uuid.UUID,
    company_id: uuid.UUID, person_ids: list[uuid.UUID],
) -> dict[uuid.UUID, tuple[int, datetime]]:
    groups = visible_company_groups(user, agency_id, company_id).subquery()
    rows = (await session.execute(select(Count.traveller_id, func.sum(Count.submission_count),
        func.max(Count.latest_submission_at)).join(groups, groups.c.id == Count.group_id).where(
        Count.agency_id == agency_id, Count.company_id == company_id, Count.traveller_id.in_(person_ids))
        .group_by(Count.traveller_id))).all()
    return {identifier: (count, latest) for identifier, count, latest in rows}
