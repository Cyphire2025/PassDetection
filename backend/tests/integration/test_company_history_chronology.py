"""Historical source registration order must not replace actual trip chronology."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import Response
from sqlalchemy import select

from app.infrastructure.database.models import ClientGroupModel as Group
from app.infrastructure.database.traveller_reuse_models import TravellerMatchCaseModel as MatchCase
from app.infrastructure.database.traveller_reuse_models import TravellerParticipationModel as Participation
from app.presentation.api.v1.routes.company_source_documents import person_sources
from app.presentation.api.v1.routes.company_traveller_history import company_traveller_history
from tests.integration.test_company_people import people_fixture
from tests.unit.application.test_traveller_enrollment import _source


@pytest.mark.asyncio
async def test_original_submissions_use_source_dates_across_pages_and_keep_unknown_dates(db_session, test_settings):
    ctx, person, user = await people_fixture(db_session)
    now = datetime.now(UTC)
    sources = [ctx.source, *[_source(ctx.group) for _ in range(3)]]
    db_session.add_all(sources[1:])
    for position, source in enumerate(sources):
        source.created_at = now - timedelta(days=position + 1)
    await db_session.flush()
    cases = [MatchCase(agency_id=person.agency_id, company_id=person.company_id,
        traveller_id=person.id, group_id=ctx.group.id, source_kind="passport_submission",
        source_row_key=str(source.id), source_created_at=source.created_at if position < 2 else None,
        created_at=now - timedelta(minutes=4 - position), status="resolved", reason_code="historical_registration")
        for position, source in enumerate(sources)]
    db_session.add_all(cases)
    await db_session.flush()
    cursor, found = None, []
    for _ in range(4):
        page = await person_sources(company_id=person.company_id, person_id=person.id,
            agency_id=person.agency_id, cursor=cursor, page_size=1, user=user,
            session=db_session, settings=test_settings)
        assert len(page.items) == 1
        found.append(page.items[0].id)
        cursor = page.next_cursor
    assert found[:2] == [sources[0].id, sources[1].id]
    assert set(found[2:]) == {sources[2].id, sources[3].id}
    assert len(set(found)) == 4 and cursor is None
    assert cases[0].created_at < cases[1].created_at
    assert [source.created_at for source in sources] == [now - timedelta(days=position + 1) for position in range(4)]


@pytest.mark.asyncio
async def test_person_trip_groups_use_trip_dates_with_undated_groups_last(db_session, test_settings):
    ctx, person, user = await people_fixture(db_session)
    original = await db_session.scalar(select(Participation).where(Participation.traveller_id == person.id))
    original.trip_started_at = date(2024, 1, 1)
    dates = [date(2025, 1, 1), date(2026, 1, 1), None]
    groups = [Group(agency_id=person.agency_id, company_id=person.company_id,
        company_revision=1, token=uuid.uuid4().hex, name=f"Synthetic trip {position}", travel_date=value)
        for position, value in enumerate(dates)]
    db_session.add_all(groups)
    await db_session.flush()
    now = datetime.now(UTC)
    trips = [Participation(agency_id=person.agency_id, company_id=person.company_id,
        traveller_id=person.id, group_id=group.id, source_kind="historical_source", profile_revision=1,
        contact_revision=1, status="accepted", question_version="historical",
        idempotency_key=f"chronology-{group.id}", trip_started_at=value,
        created_at=now - timedelta(days=position + 1)) for position, (group, value) in enumerate(zip(groups, dates, strict=True))]
    db_session.add_all(trips)
    await db_session.flush()
    cursor, found = None, []
    for _ in range(4):
        page = await company_traveller_history(company_id=person.company_id, traveller_id=person.id,
            response=Response(), agency_id=person.agency_id, cursor=cursor, page_size=1,
            user=user, session=db_session, settings=test_settings)
        assert len(page.items) == 1
        found.append(page.items[0].group_id)
        cursor = page.next_cursor
    assert found == [groups[1].id, groups[0].id, ctx.group.id, groups[2].id]
    assert cursor is None and trips[0].created_at > trips[1].created_at
