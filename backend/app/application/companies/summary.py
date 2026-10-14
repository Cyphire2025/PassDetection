"""Company totals use scoped aggregates, never hydrated history or phone counts.

Four aggregate statements return constant-sized results. Exact counts visit the
company's visible groups and source rows, with indexed membership/match probes;
app memory is O(1). Database work is O(G + P + S log P + R log M), plus the
database's distinct-person aggregation, for groups G, participations P, collected
submissions S, roster source rows R and match cases M. No claim of constant-time
counts is made: very large individual companies still need measured query plans.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import String, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from app.application.companies.access import visible_company_groups
from app.application.companies.participation_scope import live_participation_profile
from app.application.companies.trip_phase import completed_company_trip
from app.application.travellers.reconciliation_sources import roster_source_query
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, User
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerMatchCaseModel,
    TravellerParticipationModel,
    TravellerReconciliationJobModel,
)


@dataclass(frozen=True, slots=True)
class CompanyTotals:
    active_groups: int
    closed_groups: int
    archived_groups: int
    total_groups: int
    collected_records: int
    unique_travellers: int
    trip_participations: int
    unresolved_historical_records: int
    identity_totals_partial: bool
    completed_groups: int
    current_groups: int
    passenger_trips_completed: int
    passenger_trips_total: int


def _source_key(identifier: ColumnElement[uuid.UUID]) -> ColumnElement[str]:
    # PostgreSQL UUID text has hyphens, SQLite's test UUID storage does not.
    # Normalize the source side only, retaining exact indexed match-key lookup.
    value = func.replace(cast(identifier, String), "-", "")
    return (cast(func.substr(value, 1, 8), String) + "-" + func.substr(value, 9, 4) + "-"
        + func.substr(value, 13, 4) + "-" + func.substr(value, 17, 4) + "-" + func.substr(value, 21, 12))


def _unresolved_roster(kind: str, agency_id: uuid.UUID, company_id: uuid.UUID,
    visible: Select[tuple[uuid.UUID]],
) -> ColumnElement[int]:
    source = roster_source_query(kind, agency_id)
    link, match, participation = ClientGroupWhatsAppBroadcastLinkModel, TravellerMatchCaseModel, TravellerParticipationModel
    accepted = select(participation.id).where(participation.agency_id == agency_id,
        participation.company_id == company_id, participation.group_id == match.group_id,
        participation.traveller_id == match.traveller_id, participation.status == "accepted",
        live_participation_profile()).correlate(match).exists()
    resolved = select(match.id).where(match.agency_id == agency_id, match.company_id == company_id,
        match.group_id == link.client_group_id, match.source_kind == kind,
        match.source_row_key == _source_key(source.selected_columns.id),
        match.status == "resolved", accepted).correlate(*source.get_final_froms()).exists()
    return source.with_only_columns(func.count()).where(
        link.client_group_id.in_(visible), ~resolved).scalar_subquery()


async def company_totals(session: AsyncSession, *, user: User, agency_id: uuid.UUID,
    company_id: uuid.UUID, now: datetime | None = None,
) -> CompanyTotals:
    scope = visible_company_groups(user, agency_id, company_id)
    completed = completed_company_trip(now or datetime.now(UTC))
    visible = scope.with_only_columns(ClientGroupModel.id)
    completed_ids = visible.where(completed)
    lifecycle = scope.with_only_columns(ClientGroupModel.status, completed.label("completed")).subquery()
    lifecycle_rows = (await session.execute(select(lifecycle.c.status, func.count(),
        func.count(case((lifecycle.c.completed, 1)))).group_by(lifecycle.c.status))).all()
    counts = {status: int(count) for status, count, _ in lifecycle_rows}
    completed_count = sum(int(count) for _, _, count in lifecycle_rows)
    participation, source = TravellerParticipationModel, PassportSubmissionModel
    member_scope = (participation.agency_id == agency_id, participation.company_id == company_id,
        participation.group_id.in_(visible), live_participation_profile())
    accepted = participation.status == "accepted"
    membership = (await session.execute(select(
        func.count(case((accepted, participation.id))),
        func.count(func.distinct(case((accepted, participation.traveller_id)))),
        func.count(case((participation.status.in_(("pending", "submitted")), participation.id))),
        func.count(case((accepted & participation.group_id.in_(completed_ids), participation.id))),
    ).where(*member_scope))).one()
    resolved = select(participation.id).where(*member_scope, accepted,
        participation.source_submission_id == source.id).correlate(source).exists()
    submissions = (await session.execute(select(func.count(source.id),
        func.count(case((~resolved, source.id)))).where(source.agency_id == agency_id,
        source.group_id.in_(visible), source.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES)))).one()
    job, match = TravellerReconciliationJobModel, TravellerMatchCaseModel
    jobs_pending = select(job.id).where(job.agency_id == agency_id, job.company_id == company_id,
        job.group_id.in_(visible), job.status.in_(("queued", "running", "failed"))).exists()
    matches_pending = select(match.id).where(match.agency_id == agency_id, match.company_id == company_id,
        match.group_id.in_(visible), match.status.not_in(("resolved", "purged"))).exists()
    roster = (await session.execute(select(
        _unresolved_roster("whatsapp_recipient", agency_id, company_id, visible),
        _unresolved_roster("whatsapp_rejected", agency_id, company_id, visible),
        jobs_pending, matches_pending,
    ))).one()
    unresolved = int(submissions[1]) + int(roster[0]) + int(roster[1])
    return CompanyTotals(active_groups=counts.get("active", 0), closed_groups=counts.get("closed", 0),
        archived_groups=counts.get("archived", 0), total_groups=sum(counts.values()),
        collected_records=int(submissions[0]), unique_travellers=int(membership[1]),
        trip_participations=int(membership[0]), unresolved_historical_records=unresolved,
        identity_totals_partial=bool(unresolved or membership[2] or roster[2] or roster[3]),
        completed_groups=completed_count, current_groups=sum(counts.values()) - completed_count,
        passenger_trips_completed=int(membership[3]), passenger_trips_total=int(membership[0]))
