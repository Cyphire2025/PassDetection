"""Real persisted refresh jobs cannot use expired or cancelled worker authority."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos import revision_refresh, revision_runtime
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)


async def _refresh_job(env, *, condition, enrolled):
    now = datetime.now(UTC)
    job_id = uuid.uuid4()
    async with env.sessions() as session, session.begin():
        enrollment = await session.scalar(select(MyPhotoEnrollmentModel))
        if enrolled:
            enrollment.status = "enrolled"
            enrollment.reference_version = 1
            enrollment.enrolled_at = now - timedelta(seconds=10)
            enrollment.provider_name = "development"
            enrollment.provider_reference_handle = "synthetic-reference"
        job = MyPhotoJobModel(
            id=job_id,
            gallery_id=env.gallery_id,
            agency_id=enrollment.agency_id,
            group_id=enrollment.group_id,
            job_type="refresh_searches",
            target_revision=1,
            status="running" if condition != "other_status" else "retrying",
            lease_owner="synthetic-worker" if condition != "other_owner" else "replacement-worker",
            lease_expires_at=now + timedelta(seconds=-5 if condition == "expired" else 30),
            cancellation_requested_at=now if condition == "cancelled" else None,
            total_count=1,
            idempotency_key="synthetic-refresh-authority",
            correlation_id=uuid.uuid4().hex,
        )
        session.add(job)
    return job_id


@pytest.mark.parametrize("enrolled", [False, True])
@pytest.mark.parametrize(
    "condition", ["current", "expired", "cancelled", "other_owner", "other_status"]
)
async def test_refresh_requires_current_uncancelled_lease(
    photo_database, monkeypatch, enrolled, condition
):
    env = photo_database
    job_id = await _refresh_job(env, condition=condition, enrolled=enrolled)
    monkeypatch.setattr(revision_runtime, "AsyncSessionFactory", env.sessions)
    result = await revision_runtime.execute_refresh_fanout(
        job_id=job_id, lease_owner="synthetic-worker", settings=env.settings
    )
    async with env.sessions() as session:
        job = await session.get(MyPhotoJobModel, job_id)
        searches = await session.scalar(select(func.count(MyPhotoSearchRunModel.id)))
        if condition == "current":
            assert result.state == "succeeded"
            assert job.status == "succeeded"
            assert searches == int(enrolled)
        else:
            assert result.state == "lease_lost"
            assert job.status == ("retrying" if condition == "other_status" else "running")
            assert searches == 0
            assert job.processed_count == 0


async def test_refresh_uses_gallery_job_lock_order(photo_database, monkeypatch):
    env = photo_database
    job_id = await _refresh_job(env, condition="current", enrolled=False)
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

    sessions = async_sessionmaker(
        env.sessions.kw["bind"], class_=RecordingSession, expire_on_commit=False
    )
    monkeypatch.setattr(revision_runtime, "AsyncSessionFactory", sessions)
    result = await revision_runtime.execute_refresh_fanout(
        job_id=job_id, lease_owner="synthetic-worker", settings=env.settings
    )
    assert result.state == "succeeded"
    assert [table for table, _sql in locks[:2]] == ["my_photo_galleries", "my_photo_jobs"]
    assert all("FOR UPDATE" in sql for _table, sql in locks)


@pytest.mark.parametrize("boundary", ["enrollments", "search_lookup", "parent_flush"])
async def test_refresh_rechecks_deadline_after_database_await(photo_database, monkeypatch, boundary):
    env = photo_database
    job_id = await _refresh_job(env, condition="current", enrolled=boundary != "enrollments")
    async with env.sessions() as session:
        expiry = (await session.get(MyPhotoJobModel, job_id)).lease_expires_at.replace(tzinfo=UTC)
    clock = [datetime.now(UTC)]
    crossed = False

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    class ExpiringSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            nonlocal crossed
            result = await super().execute(statement, *args, **kwargs)
            entity = statement.column_descriptions[0].get("entity")
            if (boundary == "enrollments" and entity is MyPhotoEnrollmentModel) or (
                boundary == "search_lookup" and entity is MyPhotoSearchRunModel
            ):
                crossed = True
                clock[0] = expiry + timedelta(seconds=1)
            return result

        async def flush(self, *args, **kwargs):
            nonlocal crossed
            inserting_search = any(isinstance(row, MyPhotoSearchRunModel) for row in self.new)
            await super().flush(*args, **kwargs)
            if boundary == "parent_flush" and inserting_search:
                crossed = True
                clock[0] = expiry + timedelta(seconds=1)

    monkeypatch.setattr(revision_refresh, "datetime", Clock)
    monkeypatch.setattr(
        revision_runtime,
        "AsyncSessionFactory",
        async_sessionmaker(env.sessions.kw["bind"], class_=ExpiringSession, expire_on_commit=False),
    )
    result = await revision_runtime.execute_refresh_fanout(
        job_id=job_id, lease_owner="synthetic-worker", settings=env.settings
    )
    assert crossed
    assert result.state == "lease_lost"
    async with env.sessions() as session:
        assert await session.scalar(select(func.count(MyPhotoSearchRunModel.id))) == 0
        job = await session.get(MyPhotoJobModel, job_id)
        assert job.status == "running" and job.processed_count == 0


@pytest.mark.parametrize("change", ["disabled", "revision"])
async def test_stale_gallery_retains_existing_terminal_category(photo_database, monkeypatch, change):
    env = photo_database
    job_id = await _refresh_job(env, condition="current", enrolled=True)
    async with env.sessions() as session, session.begin():
        gallery = await session.get(MyPhotoGalleryModel, env.gallery_id)
        if change == "disabled":
            gallery.feature_enabled = False
        else:
            gallery.published_revision = 2
    monkeypatch.setattr(revision_runtime, "AsyncSessionFactory", env.sessions)
    result = await revision_runtime.execute_refresh_fanout(
        job_id=job_id, lease_owner="synthetic-worker", settings=env.settings
    )
    assert result.state == "failed"
    async with env.sessions() as session:
        job = await session.get(MyPhotoJobModel, job_id)
        assert job.status == "failed"
        assert job.stable_error_code == "REFRESH_GALLERY_STALE"
        assert await session.scalar(select(func.count(MyPhotoSearchRunModel.id))) == 0
