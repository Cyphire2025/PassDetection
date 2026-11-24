"""Persisted search admission prevents duplicate, early and stale provider work."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.application.my_photos.providers import FaceSearchResult
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos import worker_runtime
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)
from tests.integration.test_my_photos_search_failure_authority import _queued_search


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("missing_search", "noop"),
        ("completed", "noop"),
        ("missing_job", "failed"),
        ("cancelled", "cancelled"),
        ("delayed", "retrying"),
        ("leased", "lease_busy"),
        ("search_exhausted", "failed"),
        ("job_exhausted", "failed"),
        ("disabled", "failed"),
        ("revision_changed", "failed"),
        ("reference_changed", "failed"),
        ("consent_revoked", "failed"),
        ("window_closed", "failed"),
        ("redelivery", "succeeded"),
    ],
)
async def test_search_admission_rechecks_durable_eligibility_before_provider(
    photo_database, monkeypatch, condition, expected
):
    env = photo_database
    search_id, job_id = await _queued_search(env)
    monkeypatch.setattr(worker_runtime, "AsyncSessionFactory", env.sessions)
    now = datetime.now(UTC)
    async with env.sessions() as session, session.begin():
        search = await session.get(MyPhotoSearchRunModel, search_id)
        job = await session.get(MyPhotoJobModel, job_id)
        gallery = await session.get(MyPhotoGalleryModel, env.gallery_id)
        enrollment = await session.scalar(select(MyPhotoEnrollmentModel))
        if condition == "completed":
            search.status, job.status = "complete", "succeeded"
        elif condition == "missing_job":
            await session.execute(delete(MyPhotoJobModel).where(MyPhotoJobModel.id == job_id))
        elif condition == "cancelled":
            job.cancellation_requested_at = now
        elif condition == "delayed":
            job.status = "retrying"
            job.next_attempt_at = now + timedelta(seconds=300)
        elif condition == "leased":
            search.status, job.status = "searching", "running"
            search.lease_owner = job.lease_owner = "synthetic-other-worker"
            search.lease_expires_at = job.lease_expires_at = now + timedelta(seconds=300)
        elif condition == "search_exhausted":
            search.attempt_count = search.max_attempts
        elif condition == "job_exhausted":
            job.attempt_count = job.max_attempts
        elif condition == "disabled":
            gallery.feature_enabled = False
        elif condition == "revision_changed":
            gallery.published_revision = gallery.face_index_version = gallery.media_version = 2
        elif condition == "reference_changed":
            enrollment.reference_version = 2
        elif condition == "consent_revoked":
            enrollment.status, enrollment.revoked_at = "revoked", now
        elif condition == "window_closed":
            gallery.availability_starts_at = now - timedelta(days=2)
            gallery.availability_ends_at = now - timedelta(seconds=1)
        elif condition == "redelivery":
            search.attempt_count = job.attempt_count = 1
    calls = []

    class Provider:
        async def search(self, request):
            calls.append(request)
            return FaceSearchResult((), "synthetic-model")

    result = await worker_runtime.execute_search_job(
        uuid.uuid4() if condition == "missing_search" else search_id,
        settings=env.settings,
        providers=SimpleNamespace(face_search=Provider()),
        lease_owner="synthetic-new-search-worker",
    )
    assert result.state == expected
    assert len(calls) == int(condition == "redelivery")
    async with env.sessions() as session:
        search = await session.get(MyPhotoSearchRunModel, search_id)
        job = await session.get(MyPhotoJobModel, job_id)
        if condition == "missing_search":
            assert search.status == job.status == "queued"
        elif condition == "leased":
            assert search.lease_owner == job.lease_owner == "synthetic-other-worker"
            assert result.retry_after_seconds > 0
        elif condition == "redelivery":
            assert search.attempt_count == job.attempt_count == 2
            assert search.status == "complete" and job.status == "succeeded"
            assert (
                await worker_runtime.execute_search_job(
                    search_id,
                    settings=env.settings,
                    providers=SimpleNamespace(face_search=Provider()),
                )
            ).state == "noop"
            assert len(calls) == 1
