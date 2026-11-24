"""Search provider outcomes cannot write after either durable lease expires."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import FaceSearchResult, ProviderFaceMatch
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoJobModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos import search_job_queries, worker_runtime
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)


async def _queued_search(env, *, idempotency_key="synthetic-search"):
    now = datetime.now(UTC)
    search_id, job_id = uuid.uuid4(), uuid.uuid4()
    async with env.sessions() as session, session.begin():
        enrollment = await session.scalar(select(MyPhotoEnrollmentModel))
        enrollment.status = "enrolled"
        enrollment.provider_reference_handle = "synthetic-reference"
        enrollment.reference_version = 1
        enrollment.enrolled_at = now
        session.add(
            MyPhotoSearchRunModel(
                id=search_id,
                enrollment_id=enrollment.id,
                passenger_identity_id=enrollment.passenger_identity_id,
                gallery_id=env.gallery_id,
                agency_id=enrollment.agency_id,
                group_id=enrollment.group_id,
                gallery_revision=1,
                face_index_version=1,
                enrollment_version=1,
                idempotency_key=idempotency_key,
                total_face_count=1,
                correlation_id=uuid.uuid4().hex,
            )
        )
        await session.flush()
        session.add(
            MyPhotoJobModel(
                id=job_id,
                search_run_id=search_id,
                gallery_id=env.gallery_id,
                agency_id=enrollment.agency_id,
                group_id=enrollment.group_id,
                job_type="search_passenger",
                status="queued",
                idempotency_key=idempotency_key,
                total_count=1,
                correlation_id=uuid.uuid4().hex,
            )
        )
    return search_id, job_id


@pytest.mark.parametrize("outcome", ["unavailable", "invalid", "success"])
@pytest.mark.parametrize(
    "change", [None, "expired_search", "expired_job", "cancelled", "reassigned"]
)
async def test_search_outcome_respects_both_current_lease_boundaries(
    photo_database, monkeypatch, outcome, change
):
    env = photo_database
    search_id, job_id = await _queued_search(env)
    monkeypatch.setattr(worker_runtime, "AsyncSessionFactory", env.sessions)

    class Provider:
        async def search(self, _request):
            if change is not None:
                async with env.sessions() as session, session.begin():
                    if change == "expired_search":
                        await session.execute(
                            update(MyPhotoSearchRunModel)
                            .where(MyPhotoSearchRunModel.id == search_id)
                            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
                        )
                    else:
                        values = {
                            "expired_job": {
                                "lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)
                            },
                            "cancelled": {"cancellation_requested_at": datetime.now(UTC)},
                            "reassigned": {"lease_owner": "synthetic-new-search-worker"},
                        }[change]
                        await session.execute(
                            update(MyPhotoJobModel)
                            .where(MyPhotoJobModel.id == job_id)
                            .values(**values)
                        )
            if outcome == "unavailable":
                raise MyPhotosUnavailable("MY_PHOTOS_PROVIDER_UNAVAILABLE", "Synthetic failure.")
            return FaceSearchResult(
                matches=(ProviderFaceMatch("synthetic-face", float("nan")),)
                if outcome == "invalid"
                else (),
                provider_model_version="synthetic-model",
            )

    result = await worker_runtime.execute_search_job(
        search_id,
        settings=env.settings,
        providers=SimpleNamespace(face_search=Provider()),
        lease_owner="synthetic-original-search-worker",
    )
    async with env.sessions() as session:
        search = await session.get(MyPhotoSearchRunModel, search_id)
        job = await session.get(MyPhotoJobModel, job_id)
        if change is not None:
            assert result.state == "lease_lost"
            assert search.status == "searching" and job.status == "running"
            assert search.stable_error_code is None and job.stable_error_code is None
            assert job.next_attempt_at is None
        elif outcome == "unavailable":
            assert result.state == job.status == "retrying" and search.status == "queued"
        elif outcome == "invalid":
            assert result.state == search.status == job.status == "failed"
        else:
            assert result.state == job.status == "succeeded" and search.status == "complete"


@pytest.mark.parametrize("outcome", ["success", "unavailable"])
async def test_search_rechecks_expiry_after_last_claim_row_lock(
    photo_database, monkeypatch, outcome
):
    env = photo_database
    search_id, job_id = await _queued_search(env)
    started = False
    after_lock = False
    initial = datetime.now(UTC)

    class Clock:
        @staticmethod
        def now(tz=None):
            assert tz is UTC
            return initial + timedelta(
                seconds=env.settings.my_photos.job_lease_seconds + 60 if after_lock else 0
            )

    class RecordingSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            nonlocal after_lock
            result = await super().execute(statement, *args, **kwargs)
            if (
                started
                and getattr(statement, "_for_update_arg", None) is not None
                and statement.column_descriptions[0]["entity"] is MyPhotoJobModel
            ):
                after_lock = True
            return result

    monkeypatch.setattr(search_job_queries, "datetime", Clock)
    monkeypatch.setattr(
        worker_runtime,
        "AsyncSessionFactory",
        async_sessionmaker(
            env.sessions.kw["bind"], class_=RecordingSession, expire_on_commit=False
        ),
    )

    class Provider:
        async def search(self, _request):
            nonlocal started
            started = True
            if outcome == "unavailable":
                raise MyPhotosUnavailable("MY_PHOTOS_PROVIDER_UNAVAILABLE", "Synthetic failure.")
            return FaceSearchResult((), "synthetic-model")

    result = await worker_runtime.execute_search_job(
        search_id,
        settings=env.settings,
        providers=SimpleNamespace(face_search=Provider()),
        lease_owner="synthetic-waiting-worker",
    )
    assert after_lock and result.state == "lease_lost"
    async with env.sessions() as session:
        search = await session.get(MyPhotoSearchRunModel, search_id)
        job = await session.get(MyPhotoJobModel, job_id)
        assert search.status == "searching" and job.status == "running"
        assert search.stable_error_code is None and job.stable_error_code is None
