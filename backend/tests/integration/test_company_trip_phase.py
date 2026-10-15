"""Return-date reporting is independent from intake closure and archiving."""
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.application.companies.summary import company_totals
from app.application.companies.trip_phase import completed_company_trip
from app.domain.entities.entities import GroupStatus
from app.infrastructure.database.models import ClientGroupModel
from tests.integration.test_company_directory import company, seed_user
from tests.integration.test_company_summary import assigned_group, membership, person


@pytest.mark.asyncio
async def test_completed_counts_use_return_day_not_closed_or_archived_status(db_session):
    user = await seed_user(db_session)
    client = await company(db_session, user)
    rows = [await assigned_group(db_session, user, client, status) for status in
            (GroupStatus.ACTIVE, GroupStatus.CLOSED, GroupStatus.ARCHIVED, GroupStatus.CLOSED)]
    rows[0].return_date = date(2026, 10, 13)
    rows[1].return_date = date(2026, 10, 14)
    rows[2].return_date = date(2026, 10, 15)
    rows[3].return_date = None
    rows[3].travel_date = date(2026, 1, 1)  # No invented end date.
    profile = await person(db_session, rows[0])
    for group in rows:
        await membership(db_session, group, profile)
    await db_session.flush()
    totals = await company_totals(db_session, user=user, agency_id=client.agency_id,
        company_id=client.id, now=datetime(2026, 10, 14, 12, tzinfo=UTC))
    assert totals.completed_groups == 1
    assert totals.current_groups == 3
    assert totals.total_groups == 4
    assert totals.passenger_trips_completed == 1
    assert totals.passenger_trips_total == 4
    assert totals.trip_participations == 4 and totals.unique_travellers == 1


@pytest.mark.asyncio
async def test_group_phase_uses_group_timezone_and_keeps_return_day_active(db_session):
    user = await seed_user(db_session)
    client = await company(db_session, user)
    india, america, undated = [await assigned_group(db_session, user, client) for _ in range(3)]
    india.timezone, america.timezone = "Asia/Kolkata", "America/New_York"
    india.return_date = america.return_date = date(2026, 10, 14)
    undated.return_date = None
    await db_session.flush()
    complete = completed_company_trip(datetime(2026, 10, 14, 20, tzinfo=UTC))
    query = select(ClientGroupModel.id).where(ClientGroupModel.company_id == client.id)
    assert set(await db_session.scalars(query.where(complete))) == {india.id}
    assert set(await db_session.scalars(query.where(~complete))) == {america.id, undated.id}
