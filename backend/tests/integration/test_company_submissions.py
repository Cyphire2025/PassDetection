"""Ordinary company records combine groups without requiring identity enrollment."""
from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, UserRole
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    EntityNotFoundError,
    ValidationError,
)
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.traveller_reuse_models import TravellerProfileModel
from app.presentation.api.v1.routes.company_submissions import company_submissions, router
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.middleware.error_handler import register_exception_handlers
from tests.integration.test_company_directory import company, seed_user


async def group(session, user, client, *, status="active", deleted_at=None, name="Trip"):
    row = ClientGroupModel(id=uuid.uuid4(), agency_id=user.agency_id, company_id=client.id, company_revision=1,
                           created_by_user_id=user.id, name=name, token=uuid.uuid4().hex, status=status,
                           deleted_at=deleted_at)
    session.add(row)
    await session.flush()
    return row


async def submission(session, trip, *, status="confirmed", name="Same Person", created_at=None, **values):
    row = PassportSubmissionModel(id=uuid.uuid4(), agency_id=trip.agency_id, group_id=trip.id,
                                  client_name=name, status=status, image_s3_key="private/document.png",
                                  created_at=created_at or datetime.now(UTC) - timedelta(days=1), **values)
    session.add(row)
    await session.flush()
    return row


async def page(session, settings, owner, client, **overrides):
    values = dict(company_id=client.id, agency_id=owner.agency_id, search="", cursor=None, page_size=25,
                  user=owner, session=session, settings=settings)
    return await company_submissions(**{**values, **overrides})


@pytest.mark.asyncio
async def test_all_visible_groups_and_office_statuses_combine_without_enrollment(db_session: AsyncSession, test_settings: Settings):
    user = await seed_user(db_session)
    client = await company(db_session, user)
    expected = set()
    for lifecycle in ("active", "closed", "archived"):
        trip = await group(db_session, user, client, status=lifecycle, name=f"{lifecycle} trip")
        for status in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES:
            expected.add((await submission(db_session, trip, status=status)).id)
    assert await db_session.scalar(select(func.count()).select_from(TravellerProfileModel)) == 0
    result = await page(db_session, test_settings, user, client)
    assert {item.id for item in result.items} == expected
    assert len(result.items) == 18  # Ordinary duplicate names on different trips stay separate records.
    assert {item.group_name for item in result.items} == {"active trip", "closed trip", "archived trip"}
    assert not result.has_more and result.next_cursor is None


@pytest.mark.asyncio
async def test_deleted_old_data_drafts_other_companies_and_tenants_are_excluded(db_session: AsyncSession, test_settings: Settings):
    user, foreign_user = await seed_user(db_session), await seed_user(db_session)
    client, other = await company(db_session, user), await company(db_session, user, "Other client")
    foreign = await company(db_session, foreign_user)
    visible = await group(db_session, user, client)
    expected = await submission(db_session, visible)
    for status in ("uploaded", "processing", "failed", "extracted"):
        await submission(db_session, visible, status=status)
    for trip in (await group(db_session, user, client, status="deleted"),
                 await group(db_session, user, client, status="active", deleted_at=datetime.now(UTC)),
                 await group(db_session, user, other), await group(db_session, foreign_user, foreign)):
        await submission(db_session, trip)
    result = await page(db_session, test_settings, user, client)
    assert [item.id for item in result.items] == [expected.id]
    with pytest.raises(EntityNotFoundError):
        await page(db_session, test_settings, foreign_user, client)
    with pytest.raises(AuthorizationError):
        await page(db_session, test_settings, user, client, agency_id=foreign_user.agency_id)
    with pytest.raises(AuthorizationError):
        await page(db_session, test_settings, replace(user, role=UserRole.AGENCY_STAFF), client)


@pytest.mark.asyncio
async def test_name_search_is_literal_and_never_returns_phone_or_passport_only_matches(db_session: AsyncSession, test_settings: Settings):
    user = await seed_user(db_session)
    client = await company(db_session, user)
    trip = await group(db_session, user, client)
    literal = await submission(db_session, trip, name="AL% Client")
    await submission(db_session, trip, name="Alice Client")
    confirmed = await submission(db_session, trip, name="Contact", confirmed_fields={"given_names": "Hannah", "surname": "North"})
    unicode_name = await submission(db_session, trip, name="Straße")
    await submission(db_session, trip, name="Unrelated", client_phone="123456789", extracted_fields={"passport_number": "HANNAH123"})
    assert [item.id for item in (await page(db_session, test_settings, user, client, search="al%")).items] == [literal.id]
    assert [item.id for item in (await page(db_session, test_settings, user, client, search="HANNAH")).items] == [confirmed.id]
    assert not (await page(db_session, test_settings, user, client, search="123456789")).items
    assert [item.id for item in (await page(db_session, test_settings, user, client, search="Straße")).items] == [unicode_name.id]
    with pytest.raises(ValidationError):
        await page(db_session, test_settings, user, client, search="ab")


@pytest.mark.asyncio
async def test_cursor_tie_breaker_cutoff_and_actor_company_filter_binding(db_session: AsyncSession, test_settings: Settings):
    user = await seed_user(db_session)
    client = await company(db_session, user)
    trip = await group(db_session, user, client)
    instant = datetime.now(UTC) - timedelta(days=1)
    expected = {(await submission(db_session, trip, created_at=instant)).id for _ in range(7)}
    first = await page(db_session, test_settings, user, client, page_size=2)
    assert first.has_more and first.next_cursor
    await submission(db_session, trip, created_at=datetime.now(UTC) + timedelta(seconds=1))
    ids = [item.id for item in first.items]
    cursor = first.next_cursor
    while cursor:
        result = await page(db_session, test_settings, user, client, page_size=2, cursor=cursor)
        ids.extend(item.id for item in result.items)
        cursor = result.next_cursor
    assert set(ids) == expected and len(ids) == len(set(ids))
    for changed in ({"search": "same"}, {"user": replace(user, id=uuid.uuid4())}):
        with pytest.raises(ValidationError):
            await page(db_session, test_settings, user, client, cursor=first.next_cursor, **changed)
    other = await company(db_session, user, "Other client")
    with pytest.raises(ValidationError):
        await page(db_session, test_settings, user, other, cursor=first.next_cursor)


@pytest.mark.asyncio
async def test_bounded_status_merge_keeps_all_ties_and_filters_scope_before_limits(db_session: AsyncSession, test_settings: Settings):
    user, foreign_user = await seed_user(db_session), await seed_user(db_session)
    client = await company(db_session, user)
    other = await company(db_session, user, "Other company")
    foreign = await company(db_session, foreign_user)
    trips = [await group(db_session, user, client, status=status) for status in ("active", "closed", "archived")]
    excluded = [await group(db_session, user, other), await group(db_session, foreign_user, foreign),
                await group(db_session, user, client, status="deleted")]
    instant = datetime.now(UTC) - timedelta(days=1)
    expected = []
    for status in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES:
        for index in range(9):  # Each branch has more ties than the requested K=8.
            expected.append((await submission(db_session, trips[index % len(trips)], status=status, created_at=instant)).id)
        for trip in excluded:
            # Newer invisible records must be excluded before each branch cap.
            await submission(db_session, trip, status=status, created_at=instant + timedelta(hours=1))
        await submission(db_session, trips[0], status=status, created_at=datetime.now(UTC) + timedelta(days=1))
    seen, cursor = [], None
    while True:
        result = await page(db_session, test_settings, user, client, page_size=7, cursor=cursor)
        assert len(result.items) <= 7
        seen.extend(item.id for item in result.items)
        cursor = result.next_cursor
        assert result.has_more is bool(cursor)
        if not cursor:
            break
    assert seen == sorted(expected, reverse=True)


@pytest.mark.asyncio
async def test_empty_company_keeps_two_queries_and_never_returns_neighbour_records(db_session: AsyncSession, test_settings: Settings):
    user = await seed_user(db_session)
    empty = await company(db_session, user, "Empty client")
    populated = await company(db_session, user, "Populated client")
    trip = await group(db_session, user, populated)
    for status in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES:
        await submission(db_session, trip, status=status)
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = await page(db_session, test_settings, user, empty)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result.items == [] and result.next_cursor is None and not result.has_more
    assert len(statements) == 2


@pytest.mark.asyncio
async def test_selective_projection_two_queries_and_allowlisted_http_response(db_session: AsyncSession, test_settings: Settings):
    user = await seed_user(db_session)
    client = await company(db_session, user)
    trip = await group(db_session, user, client)
    await submission(db_session, trip, client_phone="private-phone", extracted_fields={"passport_number": "private-number"})
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = await page(db_session, test_settings, user, client)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 2
    assert "LIMIT" in statements[-1]
    assert statements[-1].count("UNION ALL") == len(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES) - 1
    assert all(value not in statements[-1] for value in ("client_phone", "image_s3_key", "extracted_fields", "confirmed_fields"))
    expected_keys = {"id", "group_id", "group_name", "travel_date", "display_name", "status", "created_at"}
    assert set(result.items[0].model_dump()) == expected_keys
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/companies")
    register_exception_handlers(app)
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[get_db_session] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        url = f"/api/v1/companies/{client.id}/submissions"
        response = await http.get(url)
        assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
        assert set(response.json()["items"][0]) == expected_keys
        assert "private-phone" not in response.text and "private-number" not in response.text
        assert (await http.get(url, params={"page_size": 101})).status_code == 422
        assert (await http.get(url, params={"search": "ab"})).status_code == 422
