"""Real durable recovery is bounded, replayable and attempt-limited."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos import recovery_runtime
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)
from tests.integration.test_my_photos_search_failure_authority import _queued_search


async def test_dispatch_batch_preserves_oldest_order_bounds_and_safe_replay(
    photo_database, monkeypatch
):
    env = photo_database
    search_id, search_job_id = await _queued_search(env)
    now = datetime.now(UTC)
    identities = []
    async with env.sessions() as session, session.begin():
        search_job = await session.get(MyPhotoJobModel, search_job_id)
        search_job.created_at = now - timedelta(minutes=10)
        enrollment = await session.scalar(select(MyPhotoEnrollmentModel))
        asset = MyPhotoMediaAssetModel(
            id=uuid.uuid4(),
            gallery_id=env.gallery_id,
            agency_id=enrollment.agency_id,
            group_id=enrollment.group_id,
            immutable_asset_key="synthetic-recovery",
            media_type="photo",
            archive_reference="synthetic-original",
            original_filename="synthetic.jpg",
            mime_type="image/jpeg",
            width=640,
            height=480,
            aspect_ratio=4 / 3,
            byte_size=1234,
            checksum_sha256="a" * 64,
            published_revision=1,
            sort_rank=0,
        )
        session.add(asset)
        await session.flush()
        for index, (kind, status, due) in enumerate(
            [
                ("index_gallery", "queued", None),
                ("prepare_media", "retrying", now - timedelta(seconds=1)),
                ("refresh_searches", "running", None),
                ("index_gallery", "retrying", now + timedelta(hours=1)),
            ]
        ):
            job_id = uuid.uuid4()
            identities.append(job_id)
            session.add(
                MyPhotoJobModel(
                    id=job_id,
                    gallery_id=env.gallery_id,
                    agency_id=enrollment.agency_id,
                    group_id=enrollment.group_id,
                    job_type=kind,
                    status=status,
                    media_asset_id=asset.id if kind == "prepare_media" else None,
                    target_revision=None if kind == "prepare_media" else 1,
                    lease_owner="synthetic-old-worker" if status == "running" else None,
                    lease_expires_at=now - timedelta(seconds=1) if status == "running" else None,
                    next_attempt_at=due,
                    idempotency_key=f"synthetic-recovery-{index}",
                    created_at=now - timedelta(minutes=9) + timedelta(seconds=index),
                    correlation_id=uuid.uuid4().hex,
                )
            )
    monkeypatch.setattr(recovery_runtime, "AsyncSessionFactory", env.sessions)
    small = SimpleNamespace(
        my_photos=env.settings.my_photos.model_copy(update={"recovery_batch_size": 3})
    )
    first = await recovery_runtime.recoverable_dispatches(settings=small, now=now)
    replay = await recovery_runtime.recoverable_dispatches(settings=small, now=now)
    assert first == replay
    assert [(row.job_id, row.kind) for row in first] == [
        (search_job_id, "search"),
        (identities[0], "index"),
        (identities[1], "media"),
    ]
    assert first[0].search_run_id == search_id
    larger = await recovery_runtime.recoverable_dispatches(settings=env.settings, now=now)
    assert [row.job_id for row in larger] == [search_job_id, *identities[:3]]
    assert larger[-1].kind == "index"
    assert identities[3] not in {row.job_id for row in larger}


async def _deletion_subject(env, kind, attempts):
    now = datetime.now(UTC)
    async with env.sessions() as session, session.begin():
        enrollment = await session.scalar(select(MyPhotoEnrollmentModel))
        identity = enrollment.id
        enrollment.provider_name = "development"
        enrollment.provider_reference_handle = "synthetic-current"
        enrollment.reference_version = 2
        enrollment.enrolled_at = now
        if kind == "current":
            enrollment.status = "deleted"
            enrollment.deleted_at = now
            enrollment.deletion_idempotency_key = "synthetic-delete"
            enrollment.deletion_scope = "enrollment_only"
            enrollment.provider_deletion_status = "pending"
            enrollment.provider_deletion_requested_at = now
            enrollment.provider_deletion_attempt_count = attempts
        else:
            enrollment.status = "enrolled"
            enrollment.superseded_provider_reference_handle = "synthetic-old"
            enrollment.superseded_reference_deletion_status = "pending"
            enrollment.superseded_reference_deletion_requested_at = now
            enrollment.superseded_deletion_attempt_count = attempts
    return identity


@pytest.mark.parametrize("kind", ["current", "superseded"])
async def test_deletion_retry_exhaustion_retains_cleanup_evidence(
    photo_database, monkeypatch, kind
):
    env = photo_database
    maximum = env.settings.my_photos.provider_deletion_max_attempts
    identity = await _deletion_subject(env, kind, maximum - 1)
    monkeypatch.setattr(recovery_runtime, "AsyncSessionFactory", env.sessions)
    (claim,) = await recovery_runtime._claim_provider_deletions(env.settings)
    assert claim.attempt_count == maximum
    result = await recovery_runtime._finalize_provider_deletions(
        [recovery_runtime._DeletionOutcome(claim, False, "PROVIDER_UNAVAILABLE")], env.settings
    )
    assert (result.completed, result.retrying, result.terminal_failed) == (0, 0, 1)
    assert await recovery_runtime._claim_provider_deletions(env.settings) == ()
    async with env.sessions() as session:
        enrollment = await session.get(MyPhotoEnrollmentModel, identity)
        status = (
            "provider_deletion_status"
            if kind == "current"
            else "superseded_reference_deletion_status"
        )
        handle = (
            "provider_reference_handle"
            if kind == "current"
            else "superseded_provider_reference_handle"
        )
        assert getattr(enrollment, status) == "failed"
        assert getattr(enrollment, handle) == claim.provider_reference


@pytest.mark.parametrize("kind", ["current", "superseded"])
async def test_ordinary_deletion_failure_schedules_bounded_retry(photo_database, monkeypatch, kind):
    env = photo_database
    identity = await _deletion_subject(env, kind, 0)
    monkeypatch.setattr(recovery_runtime, "AsyncSessionFactory", env.sessions)
    (claim,) = await recovery_runtime._claim_provider_deletions(env.settings)
    before = datetime.now(UTC)
    result = await recovery_runtime._finalize_provider_deletions(
        [recovery_runtime._DeletionOutcome(claim, False, "PROVIDER_UNAVAILABLE")], env.settings
    )
    after = datetime.now(UTC)
    assert (result.completed, result.retrying, result.terminal_failed) == (0, 1, 0)
    status = (
        "provider_deletion_status" if kind == "current" else "superseded_reference_deletion_status"
    )
    next_due = (
        "provider_deletion_next_attempt_at"
        if kind == "current"
        else "superseded_deletion_next_attempt_at"
    )
    async with env.sessions() as session:
        enrollment = await session.get(MyPhotoEnrollmentModel, identity)
        assert getattr(enrollment, status) == "pending"
        due = getattr(enrollment, next_due).replace(tzinfo=UTC)
        assert before + timedelta(seconds=env.settings.my_photos.job_retry_base_seconds) <= due
        assert due <= after + timedelta(seconds=env.settings.my_photos.job_retry_max_seconds)
    assert await recovery_runtime._claim_provider_deletions(env.settings) == ()
    empty = await recovery_runtime.execute_provider_deletion_batch(
        settings=env.settings, providers=SimpleNamespace()
    )
    assert (empty.claimed, empty.completed, empty.retrying, empty.terminal_failed) == (0, 0, 0, 0)
    assert (await recovery_runtime._finalize_provider_deletions([], env.settings)).claimed == 0
