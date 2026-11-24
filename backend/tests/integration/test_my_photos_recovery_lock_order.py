"""Cancellation follows the same search-before-job order as result publication."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.database.my_photos_models import MyPhotoJobModel, MyPhotoSearchRunModel
from app.infrastructure.my_photos import recovery_runtime
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)
from tests.integration.test_my_photos_search_failure_authority import _queued_search


async def test_recovery_cancellation_locks_search_before_job(photo_database, monkeypatch):
    env = photo_database
    search_id, job_id = await _queued_search(env)
    now = datetime.now(UTC)
    async with env.sessions() as session, session.begin():
        search = await session.get(MyPhotoSearchRunModel, search_id)
        search.status = "searching"
        search.lease_owner = "synthetic-worker"
        search.lease_expires_at = now + timedelta(seconds=30)
        job = await session.get(MyPhotoJobModel, job_id)
        job.status = "running"
        job.lease_owner = "synthetic-worker"
        job.lease_expires_at = now + timedelta(seconds=30)
        job.cancellation_requested_at = now
    locks = []

    class RecordingSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            if getattr(statement, "_for_update_arg", None) is not None:
                locks.append(
                    (
                        statement.column_descriptions[0]["entity"].__tablename__,
                        str(statement.compile(dialect=postgresql.dialect())),
                    )
                )
            return await super().execute(statement, *args, **kwargs)

    monkeypatch.setattr(
        recovery_runtime,
        "AsyncSessionFactory",
        async_sessionmaker(env.sessions.kw["bind"], class_=RecordingSession, expire_on_commit=False),
    )
    assert await recovery_runtime._terminalize_requested_cancellations(env.settings, now) == 1
    async with env.sessions() as session:
        assert (await session.get(MyPhotoSearchRunModel, search_id)).status == "cancelled"
        assert (await session.get(MyPhotoJobModel, job_id)).status == "cancelled"
    assert [table for table, _sql in locks[:2]] == ["my_photo_search_runs", "my_photo_jobs"]
    assert all("FOR UPDATE" in sql for _table, sql in locks)
