"""Durable worker admission prevents duplicate or premature provider effects."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.application.my_photos.providers import MediaAvailabilityResult
from app.infrastructure.database.my_photos_models import MyPhotoGalleryModel, MyPhotoJobModel
from app.infrastructure.my_photos import operational_runtime
from tests.integration.my_photos_operational_fixtures import operational_media_scope


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("missing", "noop"),
        ("completed", "noop"),
        ("wrong_type", "noop"),
        ("delayed", "retrying"),
        ("leased", "lease_busy"),
        ("cancelled", "cancelled"),
        ("disabled", "failed"),
        ("exhausted", "failed"),
        ("expired", "succeeded"),
        ("queued", "succeeded"),
    ],
)
async def test_persisted_worker_admission_does_not_duplicate_provider_work(
    db_session, monkeypatch, condition, expected
):
    scope = await operational_media_scope(db_session, monkeypatch)
    now = datetime.now(UTC)
    async with scope.sessions() as session, session.begin():
        job = await session.get(MyPhotoJobModel, scope.job_id)
        if condition == "completed":
            job.status = "succeeded"
        elif condition == "delayed":
            job.status = "retrying"
            job.next_attempt_at = now + timedelta(seconds=300)
        elif condition in {"leased", "expired"}:
            job.status = "running"
            job.lease_owner = "synthetic-previous-worker"
            job.started_at = now - timedelta(minutes=10)
            job.lease_expires_at = now + timedelta(seconds=300 if condition == "leased" else -1)
        elif condition == "cancelled":
            job.cancellation_requested_at = now
        elif condition == "disabled":
            gallery = await session.get(MyPhotoGalleryModel, scope.gallery_id)
            gallery.feature_enabled = False
        elif condition == "exhausted":
            job.attempt_count = job.max_attempts
    calls = []

    class Media:
        async def prepare(self, request):
            calls.append(request)
            return MediaAvailabilityResult(
                state="delivery_available",
                byte_size=1234,
                checksum_sha256="a" * 64,
                delivery_version=2,
                storage_reference="synthetic-new-preview",
                content_type="image/jpeg",
                width=640,
                height=480,
            )

    result = await operational_runtime.execute_operational_job(
        uuid.uuid4() if condition == "missing" else scope.job_id,
        settings=scope.settings,
        providers=SimpleNamespace(media=Media()),
        lease_owner="synthetic-current-worker",
        allowed_job_types=frozenset({"index_gallery"}) if condition == "wrong_type" else None,
    )
    assert result.state == expected
    assert len(calls) == (1 if expected == "succeeded" else 0)
    async with scope.sessions() as session:
        job = await session.get(MyPhotoJobModel, scope.job_id)
        if condition in {"missing", "wrong_type"}:
            assert job.status == "queued" and job.lease_owner is None
        elif condition == "leased":
            assert job.status == "running" and job.lease_owner == "synthetic-previous-worker"
            assert result.retry_after_seconds >= 1
        elif condition == "delayed":
            assert job.status == "retrying" and job.attempt_count == 0
            assert result.retry_after_seconds >= 1
        elif condition == "disabled":
            assert job.status == "failed" and job.stable_error_code == "JOB_SCOPE_STALE"
        elif condition == "exhausted":
            assert job.status == "failed" and job.stable_error_code == "JOB_RETRY_EXHAUSTED"
        elif expected in {"succeeded", "cancelled"}:
            assert job.status == expected and job.lease_owner is None
