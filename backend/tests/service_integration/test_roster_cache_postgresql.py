"""Migrated PostgreSQL invalidation and real shared Redis roster behavior."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text, update

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    ManagerGroupAccessModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.passports import roster_cache as cache_module
from app.infrastructure.passports.roster_cache import RosterCache
from app.infrastructure.passports.roster_view_service import prepared_roster
from app.infrastructure.repositories.passport_submission_view_repository import (
    PassportSubmissionViewRepository,
)
from tests.service_integration.test_auth_concurrency import sessions as sessions
from tests.unit.infrastructure.test_roster_cache import prepared

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="explicit isolated PostgreSQL and Redis required")]


@pytest.fixture
async def roster(sessions):
    async with sessions() as session:
        agency_id, user_id, group_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        session.add(AgencyModel(id=agency_id, name="Synthetic roster", email=f"{agency_id}@example.test"))
        await session.flush()
        session.add(UserModel(id=user_id, agency_id=agency_id, email=f"{user_id}@example.test",
                              full_name="Synthetic reader", hashed_password="unused", role="agency_staff"))
        await session.flush()
        session.add(ClientGroupModel(id=group_id, agency_id=agency_id, created_by_user_id=user_id,
                                     name="Synthetic roster", token=uuid.uuid4().hex))
        await session.flush()
        session.add_all([PassportSubmissionModel(agency_id=agency_id, group_id=group_id,
            client_name=f"Synthetic {number:03}", image_s3_key="synthetic", status="submitted",
            extracted_fields={"passport_number": "SYN123", "place_of_issue": "Chennai"}) for number in range(120)])
        await session.commit()
        return User(id=user_id, agency_id=agency_id, email=f"{user_id}@example.test", full_name="Synthetic reader",
                    hashed_password="unused", role=UserRole.AGENCY_STAFF), group_id


async def index(session, user, group_id):
    return await prepared_roster(session, group_id=group_id, user=user, include_deleted=False,
        submission_filter="all", sort_by="name", sort_order="asc", search=None, page_size=50)


async def test_warm_cross_session_pages_skip_projection_and_changed_rows_invalidate(sessions, roster, monkeypatch):
    user, group_id = roster
    original = PassportSubmissionViewRepository.projection
    calls = 0
    async def projection(self, **kwargs):
        nonlocal calls
        calls += 1
        return await original(self, **kwargs)
    monkeypatch.setattr(PassportSubmissionViewRepository, "projection", projection)
    async with sessions() as first:
        cold, revision = await index(first, user, group_id)
    async with sessions() as second:
        warm, same = await index(second, user, group_id)
        assert same == revision and calls == 1
        assert warm.page(2).ordered_submission_ids == cold.page(2).ordered_submission_ids
        assert warm.page(2).duplicate_clusters == cold.page(2).duplicate_clusters
        assert len(warm.page(2).items) == 50
    async with sessions() as writer:
        await writer.execute(update(PassportSubmissionModel).where(PassportSubmissionModel.group_id == group_id)
                             .values(client_name="Changed synthetic"))
        await writer.commit()
    async with sessions() as third:
        changed, updated = await index(third, user, group_id)
        assert updated[0] == revision[0] + 1  # one increment for the entire bulk UPDATE
        assert calls == 2 and changed.total == 120
    # Per-request live visibility is mandatory even when a matching cache entry exists.
    user.id = uuid.uuid4()
    async with sessions() as denied:
        empty, inaccessible = await index(denied, user, group_id)
        assert inaccessible is None and empty.total == 0 and calls == 2


@pytest.mark.parametrize("model", [ManagerGroupAccessModel, CoordinatorGroupAssignmentModel, CoordinatorAssignmentModel])
async def test_every_assignment_mutation_and_rollback_advances_only_affected_group(sessions, roster, model):
    user, group_id = roster
    async with sessions() as session:
        before = await session.scalar(select(ClientGroupModel.roster_revision).where(ClientGroupModel.id == group_id))
        values = dict(id=uuid.uuid4(), agency_id=user.agency_id, group_id=group_id)
        if model is ManagerGroupAccessModel:
            values["manager_id"] = user.id
        else:
            values["coordinator_user_id"] = user.id
        if model is CoordinatorAssignmentModel:
            values["passenger_id"] = await session.scalar(select(PassportSubmissionModel.id).where(PassportSubmissionModel.group_id == group_id).limit(1))
        record = model(**values)
        session.add(record)
        await session.flush()
        assert await session.scalar(select(ClientGroupModel.roster_revision).where(ClientGroupModel.id == group_id)) == before + 1
        await session.rollback()
        assert await session.scalar(select(ClientGroupModel.roster_revision).where(ClientGroupModel.id == group_id)) == before
        session.add(model(**values))
        await session.flush()
        if model is ManagerGroupAccessModel:
            await session.execute(update(model).where(model.id == values["id"]).values(created_at=text("now()")))
        else:
            await session.execute(update(model).where(model.id == values["id"]).values(active=False))
        await session.execute(model.__table__.delete().where(model.id == values["id"]))
        assert await session.scalar(select(ClientGroupModel.roster_revision).where(ClientGroupModel.id == group_id)) == before + 3
        await session.rollback()


async def test_concurrent_uploads_do_not_deadlock_or_lose_revision_increments(sessions, roster):
    user, group_id = roster
    async with sessions() as session:
        before = await session.scalar(select(ClientGroupModel.roster_revision).where(ClientGroupModel.id == group_id))
    async def upload(number):
        async with sessions() as session:
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            session.add_all([PassportSubmissionModel(agency_id=user.agency_id, group_id=group_id,
                client_name=f"Concurrent {number}-{row}", image_s3_key="synthetic", status="submitted") for row in range(20)])
            await session.commit()
    start = time.perf_counter()
    await asyncio.wait_for(asyncio.gather(*(upload(number) for number in range(8))), 15)
    async with sessions() as session:
        after = await session.scalar(select(ClientGroupModel.roster_revision).where(ClientGroupModel.id == group_id))
        assert after == before + 8
        assert await session.scalar(text("SELECT count(*) FROM passport_submissions WHERE group_id=:id"), {"id": group_id}) == 280
    print(f"eight_concurrent_uploads_160_rows_seconds={time.perf_counter()-start:.3f}")


async def test_real_redis_global_count_bound_and_short_ttl(monkeypatch):
    host = os.getenv("REDIS_HOST", "localhost")
    assert host in {"localhost", "127.0.0.1", "redis"}
    client = Redis.from_url(f"redis://{host}:{os.getenv('REDIS_PORT', '6379')}/13")
    cache = RosterCache(client, secret="synthetic-roster-" + uuid.uuid4().hex)
    monkeypatch.setattr(cache_module, "MAX_ENTRIES", 2)
    try:
        value = prepared()
        for key in ("one", "two", "three"):
            await cache.put(key, value)
        assert await cache.get("one") is None
        assert await cache.get("two") is not None and await cache.get("three") is not None
        assert await client.zcard(cache.prefix + "index") == 2
        assert 0 < await client.ttl(cache.prefix + "three") <= 60
        # Bound total bytes independently of the entry count, atomically.
        monkeypatch.setattr(cache_module, "MAX_TOTAL_BYTES", 1)
        await cache.put("oversized", value)
        assert await cache.get("oversized") is None
    finally:
        await cache.close()


async def test_passenger_move_delete_and_group_lifecycle_invalidate_cached_views(sessions, roster):
    user, group_id = roster
    async with sessions() as reader:
        initial, before = await index(reader, user, group_id)
        assert initial.total == 120
    destination_id = uuid.uuid4()
    async with sessions() as writer:
        writer.add(ClientGroupModel(id=destination_id, agency_id=user.agency_id,
            created_by_user_id=user.id, token=uuid.uuid4().hex, name="Synthetic move destination"))
        await writer.flush()
        passenger_id = await writer.scalar(select(PassportSubmissionModel.id)
            .where(PassportSubmissionModel.group_id == group_id).limit(1))
        await writer.execute(update(PassportSubmissionModel).where(PassportSubmissionModel.id == passenger_id)
            .values(group_id=destination_id))
        await writer.commit()
    async with sessions() as reader:
        moved, after_move = await index(reader, user, group_id)
        destination, destination_revision = await index(reader, user, destination_id)
        assert moved.total == 119 and after_move[0] == before[0] + 1
        assert destination.total == 1 and destination_revision[0] == 1
    # This removes only this explicitly synthetic fixture row, never shared data.
    async with sessions() as writer:
        await writer.execute(PassportSubmissionModel.__table__.delete()
            .where(PassportSubmissionModel.id == passenger_id))
        await writer.commit()
    async with sessions() as reader:
        empty, after_delete = await index(reader, user, destination_id)
        assert empty.total == 0 and after_delete[0] == destination_revision[0] + 1
    for status, deleted_at, visible in (("closed", None, True), ("archived", None, False),
                                       ("active", datetime.now(UTC), False), ("active", None, True)):
        async with sessions() as writer:
            await writer.execute(update(ClientGroupModel).where(ClientGroupModel.id == group_id)
                .values(status=status, deleted_at=deleted_at, travel_date=datetime.now(UTC).date() + timedelta(days=30)))
            await writer.commit()
        async with sessions() as reader:
            current, revision = await index(reader, user, group_id)
            assert (revision is not None) is visible
            assert current.total == (119 if visible else 0)
            if visible:
                assert revision[0] > after_move[0]
                assert revision[1] == datetime.now(UTC).date() + timedelta(days=30)


async def test_coordinator_passenger_scope_survives_without_group_assignment_and_revocation_is_live(sessions, roster):
    user, group_id = roster
    user.role = UserRole.AGENCY_COORDINATOR
    async with sessions() as writer:
        passenger_id = await writer.scalar(select(PassportSubmissionModel.id)
            .where(PassportSubmissionModel.group_id == group_id).limit(1))
        assignment = CoordinatorAssignmentModel(id=uuid.uuid4(), agency_id=user.agency_id,
            group_id=group_id, passenger_id=passenger_id, coordinator_user_id=user.id)
        writer.add(assignment)
        await writer.commit()
    async with sessions() as reader:
        first, revision = await index(reader, user, group_id)
        assert first.total == 1 and first.ordered_submission_ids == (passenger_id,)
        assert revision is not None
    async with sessions() as reader:
        cached, same = await index(reader, user, group_id)
        assert cached.total == 1 and same == revision
    async with sessions() as writer:
        await writer.execute(update(CoordinatorAssignmentModel).where(CoordinatorAssignmentModel.id == assignment.id)
            .values(active=False))
        await writer.commit()
    async with sessions() as reader:
        denied, revision = await index(reader, user, group_id)
        assert denied.total == 0 and revision is None


async def test_same_principal_concurrent_sessions_share_one_projection(sessions, roster, monkeypatch):
    user, group_id = roster
    original = PassportSubmissionViewRepository.projection
    calls = 0

    async def projection(self, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.1)  # Ensure all contenders see the cold key.
        return await original(self, **kwargs)

    monkeypatch.setattr(PassportSubmissionViewRepository, "projection", projection)

    async def read():
        async with sessions() as session:
            value, revision = await index(session, user, group_id)
            return value.ordered_submission_ids, revision

    results = await asyncio.gather(*(read() for _ in range(8)))
    assert calls == 1
    assert all(result == results[0] for result in results)
    assert len(results[0][0]) == 120
