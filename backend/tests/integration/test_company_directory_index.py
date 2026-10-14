"""Encrypted search, resumable indexing and visible-source counters."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.companies.directory_names import prefix_digests, search_digests
from app.application.companies.directory_projection import (
    backfill_directory_page,
    ensure_directory_state,
    refresh_directory_person,
)
from app.application.companies.directory_query import DirectoryIndexChanged, company_directory_page
from app.application.companies.directory_ranks import DirectoryRankUnavailable, encode_rank
from app.infrastructure.database.company_directory_models import (
    CompanyDirectoryPersonModel as Entry,
)
from app.infrastructure.database.company_directory_models import (
    CompanyDirectoryPrefixModel as Prefix,
)
from app.infrastructure.database.company_directory_models import CompanyDirectoryQueueModel as Queue
from app.infrastructure.database.traveller_reuse_models import TravellerMatchCaseModel as Case
from app.infrastructure.database.traveller_reuse_models import TravellerProfileModel as Person
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.travellers.directory_runtime import run_company_directory_tick
from tests.unit.application.test_traveller_enrollment import _fixture


async def person(session, ctx, name, *, count=1, submitted=None):
    value = Person(agency_id=ctx.group.agency_id, company_id=ctx.group.company_id,
        display_name_ciphertext=ctx.crypto.encrypt(name), status="active", reuse_permission_status="unknown")
    session.add(value)
    await session.flush()
    session.add_all([Case(agency_id=value.agency_id, company_id=value.company_id, traveller_id=value.id,
        group_id=ctx.group.id, source_kind="passport_submission", source_row_key=str(uuid.uuid4()),
        source_created_at=submitted or datetime.now(UTC), status="resolved", reason_code="operator_historical_registration")
        for _ in range(count)])
    await session.flush()
    return value


async def page(session, ctx, **options):
    user = await UserRepository(session).get_by_id(ctx.request.actor_id)
    return await company_directory_page(session, user=user, agency_id=ctx.request.agency_id,
        company_id=ctx.request.company_id, crypto=ctx.crypto, secret="synthetic-cursor-secret",
        **{"search": "", "sort": "name_asc", "submissions": "all", "cursor": None, "page_size": 100, **options})


@pytest.mark.asyncio
async def test_prefix_search_is_bounded_encrypted_scoped_and_intersects_words(db_session):
    ctx = await _fixture(db_session)
    rows = [await person(db_session, ctx, name) for name in ("Zulu Tester", "Alpha Tester", "Alpha Other")]
    for value in rows:
        await refresh_directory_person(db_session, value.id, ctx.crypto)
    result = await page(db_session, ctx, search="al te")
    assert [row.display_name for row in result.items] == ["Alpha Tester"]
    assert (await page(db_session, ctx, search="tester al")).items == result.items
    assert not (await page(db_session, ctx, search="unmatched")).items
    assert [row.display_name for row in (await page(db_session, ctx)).items] == ["Alpha Other", "Alpha Tester", "Zulu Tester"]
    assert [row.display_name for row in (await page(db_session, ctx, sort="name_desc")).items] == ["Zulu Tester", "Alpha Tester", "Alpha Other"]
    tokens = prefix_digests("Alpha Tester", ctx.group.agency_id, ctx.group.company_id, ctx.crypto)
    assert tokens.isdisjoint(prefix_digests("Alpha Tester", uuid.uuid4(), ctx.group.company_id, ctx.crypto))
    assert len(prefix_digests("abcdefghij " * 1000, ctx.group.agency_id, ctx.group.company_id, ctx.crypto)) <= 254
    assert all(len(token) == 32 for token in tokens)
    assert all("Alpha" not in row.name_ciphertext and row.name_rank.isdigit() for row in await db_session.scalars(select(Entry)))
    assert "name" not in Prefix.__table__.c
    for text in ("a", "a" * 33, "aa bb cc dd ee ff gg hh ii"):
        with pytest.raises(ValueError, match="eight name parts"):
            search_digests(text, ctx.group.agency_id, ctx.group.company_id, ctx.crypto)


@pytest.mark.asyncio
async def test_newest_means_latest_original_submission_and_cursors_are_bound(db_session):
    ctx = await _fixture(db_session)
    now = datetime.now(UTC)
    old = await person(db_session, ctx, "Older Profile", submitted=now - timedelta(days=1))
    new = await person(db_session, ctx, "Newer Profile", submitted=now - timedelta(days=2))
    old.created_at, new.created_at = now - timedelta(days=20), now - timedelta(days=3)
    await db_session.flush()
    for value in (old, new):
        await refresh_directory_person(db_session, value.id, ctx.crypto)
    first = await page(db_session, ctx, sort="newest", page_size=1)
    assert first.items[0].id == old.id and first.has_more
    second = await page(db_session, ctx, sort="newest", page_size=1, cursor=first.next_cursor)
    assert second.items[0].id == new.id and not second.has_more
    with pytest.raises(ValueError, match="differently scoped"):
        await page(db_session, ctx, sort="name_asc", cursor=first.next_cursor)
    old.revision += 1
    old.display_name_ciphertext = ctx.crypto.encrypt("Renamed Profile")
    await db_session.flush()
    assert [row.id for row in (await page(db_session, ctx)).items] == [new.id]
    await refresh_directory_person(db_session, old.id, ctx.crypto)
    with pytest.raises(DirectoryIndexChanged):
        await page(db_session, ctx, sort="newest", cursor=first.next_cursor)
    with pytest.raises(ValueError, match="page size"):
        await page(db_session, ctx, page_size=101)


@pytest.mark.asyncio
async def test_counts_exclude_retained_snapshots_and_other_company_groups(db_session):
    ctx = await _fixture(db_session)
    one = await person(db_session, ctx, "One Source")
    many = await person(db_session, ctx, "Many Sources", count=3)
    session_case = Case(agency_id=one.agency_id, company_id=one.company_id, traveller_id=one.id,
        group_id=ctx.group.id, source_kind="passport_submission", source_row_key=str(uuid.uuid4()),
        source_created_at=datetime.now(UTC), status="resolved", reason_code="retained_trip_snapshot")
    db_session.add(session_case)
    await db_session.flush()
    for value in (one, many):
        await refresh_directory_person(db_session, value.id, ctx.crypto)
    assert [(row.id, row.submission_count) for row in (await page(db_session, ctx, submissions="one")).items] == [(one.id, 1)]
    assert [(row.id, row.submission_count) for row in (await page(db_session, ctx, submissions="multiple")).items] == [(many.id, 3)]
    assert one.revision == 1 and one.reuse_permission_status == "unknown"
    assert ctx.source.confirmed_fields["passport_number"] == "001234567"
    ctx.group.company_id = None
    await db_session.flush()
    assert not (await page(db_session, ctx)).items


@pytest.mark.asyncio
async def test_admission_coalesces_is_transactional_and_backfill_resumes(db_session):
    ctx = await _fixture(db_session)
    values = [await person(db_session, ctx, name) for name in ("First", "Second", "Third")]
    assert await db_session.scalar(select(func.count()).select_from(Queue)) == 3
    values[0].revision += 1
    await db_session.flush()
    assert await db_session.scalar(select(func.count()).select_from(Queue)) == 3
    async with db_session.begin_nested() as savepoint:
        extra = await person(db_session, ctx, "Rolled Back")
        extra_id = extra.id
        assert await db_session.get(Queue, extra_id) is not None
        await savepoint.rollback()
    assert await db_session.get(Queue, extra_id) is None
    await db_session.execute(delete(Queue))
    state = await ensure_directory_state(db_session, ctx.group.agency_id, ctx.group.company_id)
    assert await backfill_directory_page(db_session, limit=2) == 2
    previous = state.backfill_after
    assert await backfill_directory_page(db_session, limit=2) == 1
    assert state.backfill_after > previous
    assert await backfill_directory_page(db_session, limit=2) == 0 and state.backfill_complete
    assert await db_session.scalar(select(func.count()).select_from(Queue)) == 3


@pytest.mark.asyncio
async def test_local_rank_rebalance_preserves_names_and_all_rows(db_session):
    ctx = await _fixture(db_session)
    values = [await person(db_session, ctx, name) for name in ("Alpha", "Omega")]
    for value in values:
        await refresh_directory_person(db_session, value.id, ctx.crypto)
    entries = list(await db_session.scalars(select(Entry).order_by(Entry.name_rank)))
    entries[0].name_rank, entries[1].name_rank = encode_rank(1000), encode_rank(1001)
    await db_session.flush()
    middle = await person(db_session, ctx, "Middle")
    await refresh_directory_person(db_session, middle.id, ctx.crypto)
    assert [row.display_name for row in (await page(db_session, ctx)).items] == ["Alpha", "Middle", "Omega"]
    assert len({row.name_rank for row in await db_session.scalars(select(Entry))}) == 3
    assert await db_session.scalar(select(func.count()).select_from(Person)) == 3


@pytest.mark.asyncio
async def test_worker_is_bounded_replay_safe_and_reports_exhausted_retry(db_session):
    ctx = await _fixture(db_session)
    values = [await person(db_session, ctx, name) for name in ("Alpha", "Beta")]
    first_id = values[0].id
    await ensure_directory_state(db_session, ctx.group.agency_id, ctx.group.company_id)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await run_company_directory_tick(session_factory=factory, crypto=ctx.crypto) >= 2
    assert await run_company_directory_tick(session_factory=factory, crypto=ctx.crypto) == 0
    db_session.expire_all()
    assert len((await page(db_session, ctx)).items) == 2
    value = await db_session.get(Person, first_id)
    value.revision += 1
    await db_session.flush()
    queued = await db_session.get(Queue, value.id)
    queued.attempt_count = 5
    await db_session.flush()
    result = await page(db_session, ctx)
    assert result.indexing_pending and result.indexing_failed
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_hundred_person_pages_have_constant_queries_and_no_tenant_overlap(db_session):
    ctx = await _fixture(db_session)
    values = [await person(db_session, ctx, f"Synthetic {index:03}") for index in range(103)]
    for value in values:
        await refresh_directory_person(db_session, value.id, ctx.crypto)
    other = await _fixture(db_session)
    foreign = await person(db_session, other, "Synthetic 001")
    await refresh_directory_person(db_session, foreign.id, other.crypto)
    statements = []
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        first = await page(db_session, ctx)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(first.items) == 100 and first.has_more
    assert len(statements) <= 15
    second = await page(db_session, ctx, cursor=first.next_cursor)
    assert len(second.items) == 3 and not second.has_more
    assert {row.id for row in first.items + second.items} == {row.id for row in values}
    assert foreign.id not in {row.id for row in first.items}


@pytest.mark.asyncio
async def test_group_scope_change_and_case_reassignment_refresh_old_counters(db_session):
    ctx = await _fixture(db_session)
    first = await person(db_session, ctx, "First Owner")
    second = await person(db_session, ctx, "Second Owner")
    for value in (first, second):
        await refresh_directory_person(db_session, value.id, ctx.crypto)
    case = await db_session.scalar(select(Case).where(Case.traveller_id == first.id))
    case.traveller_id = second.id
    await db_session.flush()
    assert set(await db_session.scalars(select(Queue.traveller_id))) == {first.id, second.id}
    for value in (first, second):
        await refresh_directory_person(db_session, value.id, ctx.crypto)
    assert (await db_session.get(Entry, first.id)).submission_count == 0
    assert (await db_session.get(Entry, second.id)).submission_count == 2
    state = await ensure_directory_state(db_session, first.agency_id, first.company_id)
    state.backfill_complete, state.backfill_after = True, second.id
    await db_session.flush()
    generation = state.generation
    ctx.group.company_id = None
    await db_session.flush()
    await db_session.refresh(state)
    assert not state.backfill_complete and state.backfill_after is None and state.generation > generation


@pytest.mark.asyncio
async def test_out_of_order_rank_insertion_rename_and_deleted_profile(db_session):
    ctx = await _fixture(db_session)
    names = ("Alpha", "Zulu", "Delta", "Mike", "Beta", "Echo", "Charlie", "Epsilon", "Middle", "ALPHA")
    values = []
    for name in names:
        value = await person(db_session, ctx, name)
        values.append(value)
        await refresh_directory_person(db_session, value.id, ctx.crypto)
    expected = sorted(values, key=lambda row: (ctx.crypto.decrypt(row.display_name_ciphertext).upper(), str(row.id)))
    assert [row.id for row in (await page(db_session, ctx)).items] == [row.id for row in expected]
    values[0].display_name_ciphertext, values[0].revision = ctx.crypto.encrypt("November"), 2
    await db_session.flush()
    await refresh_directory_person(db_session, values[0].id, ctx.crypto)
    assert (await page(db_session, ctx, search="nov")).items[0].id == values[0].id
    assert [row.id for row in (await page(db_session, ctx, search="alpha")).items] == [values[-1].id]
    before = await db_session.scalar(select(func.count()).select_from(Case))
    values[0].status = "deleted"
    await db_session.flush()
    await refresh_directory_person(db_session, values[0].id, ctx.crypto)
    assert await db_session.get(Entry, values[0].id) is None
    assert await db_session.scalar(select(func.count()).select_from(Case)) == before
    with pytest.raises(DirectoryRankUnavailable):
        encode_rank(0)


@pytest.mark.asyncio
async def test_failed_refresh_retries_without_losing_work_or_logging_identity(db_session, monkeypatch):
    import app.infrastructure.travellers.directory_runtime as runtime

    ctx = await _fixture(db_session)
    value = await person(db_session, ctx, "Retry Person")
    identifier = value.id
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(runtime, "refresh_directory_person", AsyncMock(side_effect=RuntimeError("sensitive provider text")))
    assert await run_company_directory_tick(session_factory=factory, crypto=ctx.crypto) == 0
    db_session.expire_all()
    queued = await db_session.get(Queue, identifier)
    assert queued.attempt_count == 1 and queued.last_error_code == "RuntimeError"
    assert queued.available_at.replace(tzinfo=UTC) > datetime.now(UTC)
    assert await db_session.get(Entry, identifier) is None
