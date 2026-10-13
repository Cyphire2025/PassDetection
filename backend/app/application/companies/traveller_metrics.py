"""Bounded group metrics sharing the directory's exact visibility population.

One aggregate query for <=100 groups; O(p log h) indexed earlier-trip existence
checks for p scoped participations and h person history, O(page size) app memory.
Recognition, accepted membership and completed reuse remain separate measures.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.application.companies.access import visible_company_groups
from app.application.companies.participation_scope import live_participation_profile
from app.domain.entities.entities import User
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_reuse_models import TravellerParticipationModel


@dataclass(frozen=True, slots=True)
class GroupTravellerCounts:
    returning_travellers: int = 0
    trip_participations: int = 0
    reuse_completed: int = 0


async def group_traveller_counts(
    session: AsyncSession, *, user: User, agency_id: uuid.UUID,
    company_id: uuid.UUID, group_ids: list[uuid.UUID],
) -> dict[uuid.UUID, GroupTravellerCounts]:
    if not group_ids:
        return {}
    if len(group_ids) > 100:
        raise ValueError("Group metric page is limited to 100 groups")
    current = TravellerParticipationModel
    previous = aliased(TravellerParticipationModel)
    visible = visible_company_groups(user, agency_id, company_id).with_only_columns(ClientGroupModel.id)
    earlier = select(previous.id).where(
        previous.agency_id == agency_id, previous.company_id == company_id,
        previous.traveller_id == current.traveller_id, previous.status == "accepted",
        previous.group_id != current.group_id, previous.group_id.in_(visible),
        previous.trip_started_at < ClientGroupModel.travel_date,
    ).correlate(current, ClientGroupModel).exists()
    completed = (current.status == "accepted") & (current.confirmations["completion_key"].as_string().is_not(None)) & (
        current.confirmations["information_confirmed"].as_boolean().is_(True)
    )
    rows = (await session.execute(select(current.group_id,
        func.sum(case((earlier, 1), else_=0)),
        func.sum(case((current.status == "accepted", 1), else_=0)),
        func.sum(case((completed, 1), else_=0)),
    ).join(ClientGroupModel, (ClientGroupModel.id == current.group_id) & (ClientGroupModel.agency_id == current.agency_id))
        .where(current.agency_id == agency_id, current.company_id == company_id,
               current.group_id.in_(group_ids), current.status != "withdrawn", live_participation_profile())
        .group_by(current.group_id))).all()
    return {row[0]: GroupTravellerCounts(int(row[1]), int(row[2]), int(row[3])) for row in rows}
