from __future__ import annotations

import asyncio
import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.ai.gemini_ecr_service import EcrClassification
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.passport_ecr_models import PassportEcrCheckModel
from app.infrastructure.ecr import ECR_QUEUE, PASSPORT_ECR_TASK
from app.infrastructure.ecr import passport_runtime as runtime
from app.infrastructure.ecr.runtime import ProviderPacer
from app.infrastructure.processing.celery_app import celery_app


@pytest.fixture
async def passport_db(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'passport.sqlite').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: PassportEcrCheckModel.metadata.create_all(
                conn,
                tables=[
                    model.__table__
                    for model in (
                        AgencyModel,
                        ClientGroupModel,
                        PassportSubmissionModel,
                        PassportEcrCheckModel,
                    )
                ],
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    transaction_lock = asyncio.Lock()

    @asynccontextmanager
    async def serialized_session():
        # SQLite has no SELECT FOR UPDATE. Serialize its short DB transactions;
        # storage/provider awaits still run concurrently outside transactions.
        async with transaction_lock, factory() as session:
            yield session

    monkeypatch.setattr(runtime, "AsyncSessionFactory", serialized_session)
    yield factory
    await engine.dispose()


async def seed(factory, *, config=None, back=True, finalized=True, count=1):
    agency = AgencyModel(
        id=uuid.uuid4(), name="Synthetic agency", email=f"{uuid.uuid4()}@example.com"
    )
    group = ClientGroupModel(
        id=uuid.uuid4(),
        name="Synthetic group",
        token=uuid.uuid4().hex,
        agency_id=agency.id,
        upload_configuration=config if config is not None else {"passport_ecr_enabled": True},
    )
    submissions = [
        PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            group_id=group.id,
            client_name="Synthetic traveller",
            image_s3_key=f"front/{i}.jpg",
            passport_back_s3_key=f"back/{i}.jpg" if back else None,
            passport_cover_s3_key=f"cover/{i}.jpg",
            passport_back_cover_s3_key=f"back-cover/{i}.jpg",
            passport_photo_s3_key=f"photo/{i}.jpg",
            client_reviewed_at=runtime._now() if finalized else None,
            status="submitted",
        )
        for i in range(count)
    ]
    async with factory() as session:
        session.add_all([agency, group, *submissions])
        await session.commit()
    return agency, group, submissions


async def stage_all(factory, submissions):
    async with factory() as session:
        results = [await runtime.stage_passport_ecr_check(session, row.id) for row in submissions]
        await session.commit()
    return results


async def labels(factory, agency, submissions, **kwargs):
    async with factory() as session:
        return await runtime.passport_ecr_results(
            session, [s.id for s in submissions], agency_id=agency.id, **kwargs
        )


async def mutate(factory, model, id, **changes):
    async with factory() as session:
        row = await session.get(model, id)
        for key, value in changes.items():
            setattr(row, key, value)
        await session.commit()


def dependencies(monkeypatch, *, outcome="ECR", on_attempt=None, on_result=None, pacer_hook=None):
    content = b"synthetic back-page image fixture"
    calls = SimpleNamespace(provider=0, active=0, peak=0)
    storage = SimpleNamespace(
        stat_file=AsyncMock(
            return_value=SimpleNamespace(
                size_bytes=len(content),
                checksum_sha256=hashlib.sha256(content).hexdigest(),
            )
        ),
        get_file_range=AsyncMock(return_value=content),
    )
    pacer = SimpleNamespace(acquire=AsyncMock(side_effect=pacer_hook))

    class Classifier:
        def __init__(self, *, http_client, before_attempt):
            self.before_attempt = before_attempt

        async def classify(self, data, content_type):
            assert data == content
            await self.before_attempt()
            calls.provider += 1
            calls.active += 1
            calls.peak = max(calls.peak, calls.active)
            try:
                if on_attempt:
                    await on_attempt(self, calls)
                else:
                    await asyncio.sleep(0.002)
                if on_result:
                    await on_result()
                return EcrClassification(
                    outcome,
                    "network_error" if outcome == "ERROR" else "phrase_checked",
                    "test",
                    100,
                    2,
                    1,
                    1,
                )
            finally:
                calls.active -= 1

    redis = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(runtime, "Redis", SimpleNamespace(from_url=Mock(return_value=redis)))
    monkeypatch.setattr(runtime, "MinioStorageRepository", Mock(return_value=storage))
    monkeypatch.setattr(runtime, "ProviderPacer", Mock(return_value=pacer))
    monkeypatch.setattr(runtime, "GeminiEcrService", Classifier)
    return storage, pacer, calls


@pytest.mark.parametrize(
    "config,back,finalized,label",
    [
        ({}, True, True, "NOT_ENABLED"),
        ({"passport_ecr_enabled": False}, True, True, "NOT_ENABLED"),
        ({"passport_ecr_enabled": True, "passport_enabled": False}, True, True, "NOT_ENABLED"),
        ({"passport_ecr_enabled": True}, False, True, "NO_BACK"),
        ({"passport_ecr_enabled": True}, True, False, "PENDING"),
    ],
)
async def test_ineligible_sources_never_stage_or_contact_provider(
    passport_db, monkeypatch, config, back, finalized, label
):
    agency, _, submissions = await seed(passport_db, config=config, back=back, finalized=finalized)
    assert await stage_all(passport_db, submissions) == [False]
    provider = Mock(side_effect=AssertionError("disabled ECR created provider"))
    monkeypatch.setattr(runtime, "GeminiEcrService", provider)
    assert await runtime.process_passport_checks() == 0
    provider.assert_not_called()
    assert await labels(passport_db, agency, submissions) == {submissions[0].id: label}


@pytest.mark.parametrize(
    "outcome,label,result",
    [("ECR", "ECR", "ECR"), ("NA", "NA", "NA"), ("REVIEW", "REVIEW", "NEEDS_REVIEW")],
)
async def test_checks_only_back_page_and_persists_classification(
    passport_db, monkeypatch, outcome, label, result
):
    agency, _, submissions = await seed(passport_db)
    await stage_all(passport_db, submissions)
    storage, pacer, calls = dependencies(monkeypatch, outcome=outcome)
    assert await runtime.process_passport_checks() == 1
    assert calls.provider == 1
    pacer.acquire.assert_awaited_once()
    assert {call.args[0] for call in storage.stat_file.await_args_list} == {"back/0.jpg"}
    storage.get_file_range.assert_awaited_once_with(
        "back/0.jpg", start=0, end=len(b"synthetic back-page image fixture") - 1
    )
    assert await labels(passport_db, agency, submissions) == {submissions[0].id: label}
    async with passport_db() as session:
        job = await session.get(PassportEcrCheckModel, submissions[0].id)
        assert (job.status, job.result, job.attempts, job.provider_attempts) == (
            "completed",
            result,
            1,
            1,
        )
        assert (job.input_tokens, job.output_tokens) == (100, 3)
        assert job.lease_token is None and job.lease_expires_at is None


async def test_disabled_after_quota_wait_never_sends_request(passport_db, monkeypatch):
    agency, group, submissions = await seed(passport_db)
    await stage_all(passport_db, submissions)

    async def disable():
        await mutate(
            passport_db,
            ClientGroupModel,
            group.id,
            upload_configuration={"passport_ecr_enabled": False},
        )

    _, _, calls = dependencies(monkeypatch, pacer_hook=disable)
    await runtime.process_passport_checks()
    assert calls.provider == 0
    assert await labels(passport_db, agency, submissions) == {submissions[0].id: "NOT_ENABLED"}


async def test_disabled_between_provider_retries_blocks_second_attempt(passport_db, monkeypatch):
    _, group, submissions = await seed(passport_db)
    await stage_all(passport_db, submissions)

    async def disable_then_retry(classifier, calls):
        await mutate(
            passport_db,
            ClientGroupModel,
            group.id,
            upload_configuration={"passport_ecr_enabled": False},
        )
        await classifier.before_attempt()
        calls.provider += 1

    _, pacer, calls = dependencies(monkeypatch, on_attempt=disable_then_retry)
    await runtime.process_passport_checks()
    assert calls.provider == 1 and pacer.acquire.await_count == 2
    async with passport_db() as session:
        job = await session.get(PassportEcrCheckModel, submissions[0].id)
        assert job.status == "disabled" and job.provider_attempts == 1 and job.result is None


async def test_replaced_back_page_discards_inflight_result_and_fences_old_claim(
    passport_db, monkeypatch
):
    agency, _, submissions = await seed(passport_db)
    await stage_all(passport_db, submissions)
    old_claim = await runtime._claim(submissions[0].id)

    async def replace_back():
        await mutate(
            passport_db,
            PassportSubmissionModel,
            submissions[0].id,
            passport_back_s3_key="back/replacement.jpg",
        )

    storage, pacer, calls = dependencies(monkeypatch, on_result=replace_back)
    await runtime._process_one(old_claim, storage=storage, client=Mock(), pacer=pacer)
    assert calls.provider == 1
    with pytest.raises(runtime.PassportEcrStale):
        await runtime._save(old_claim, EcrClassification("ECR", "stale", "test"), None)
    async with passport_db() as session:
        job = await session.get(PassportEcrCheckModel, submissions[0].id)
        assert job.generation != old_claim.generation
        assert job.source_storage_key == "back/replacement.jpg"
        assert job.status == "queued" and job.result is None and job.provider_attempts == 0
    assert await labels(passport_db, agency, submissions) == {submissions[0].id: "PENDING"}


async def test_expired_lease_takeover_rejects_old_worker_result(passport_db):
    _, _, submissions = await seed(passport_db)
    await stage_all(passport_db, submissions)
    old = await runtime._claim(submissions[0].id)
    assert await runtime._claim(submissions[0].id) is None
    await mutate(
        passport_db,
        PassportEcrCheckModel,
        submissions[0].id,
        lease_expires_at=runtime._now() - timedelta(seconds=1),
    )
    new = await runtime._claim(submissions[0].id)
    assert new.token != old.token
    await runtime._save(new, EcrClassification("NA", "absent", "test"), None)
    with pytest.raises(runtime.PassportEcrStale):
        await runtime._save(old, EcrClassification("ECR", "stale", "test"), None)
    await runtime._release(old)
    async with passport_db() as session:
        assert (await session.get(PassportEcrCheckModel, submissions[0].id)).result == "NA"


async def test_export_refreshes_identity_map_and_rejects_mismatched_source_snapshot(passport_db):
    agency, group, submissions = await seed(passport_db)
    await stage_all(passport_db, submissions)
    claim = await runtime._claim(submissions[0].id)
    await runtime._save(claim, EcrClassification("ECR", "present", "test"), None)
    async with passport_db() as session:
        cached = await session.get(ClientGroupModel, group.id)
        assert cached.upload_configuration["passport_ecr_enabled"]
        assert await runtime.passport_ecr_results(
            session, [submissions[0].id], agency_id=agency.id
        ) == {submissions[0].id: "ECR"}
        await session.commit()
        await mutate(
            passport_db,
            ClientGroupModel,
            group.id,
            upload_configuration={"passport_ecr_enabled": False},
        )
        assert await runtime.passport_ecr_results(
            session, [submissions[0].id], agency_id=agency.id
        ) == {submissions[0].id: "NOT_ENABLED"}
    await mutate(
        passport_db, ClientGroupModel, group.id, upload_configuration={"passport_ecr_enabled": True}
    )
    assert await labels(
        passport_db,
        agency,
        submissions,
        expected_source_keys={submissions[0].id: "old/export-snapshot.jpg"},
    ) == {submissions[0].id: "PENDING"}
    assert await labels(passport_db, SimpleNamespace(id=uuid.uuid4()), submissions) == {}


async def test_total_provider_budget_survives_recovery_and_caps_internal_retries(
    passport_db, monkeypatch
):
    agency, _, submissions = await seed(passport_db)
    await stage_all(passport_db, submissions)
    old = await runtime._claim(submissions[0].id)
    await runtime._admit_provider_attempt(old)  # Simulate death after HTTP admission.
    await mutate(passport_db, PassportEcrCheckModel, submissions[0].id, lease_expires_at=None)

    async def retry_three_times(classifier, calls):
        for _ in range(2):
            await classifier.before_attempt()
            calls.provider += 1

    _, _, calls = dependencies(monkeypatch, on_attempt=retry_three_times, outcome="ERROR")
    assert await runtime.process_passport_checks() == 1
    assert calls.provider == 2  # 1 before crash + 2 after restart, never 3 + 3.
    assert await runtime.process_passport_checks() == 0
    async with passport_db() as session:
        job = await session.get(PassportEcrCheckModel, submissions[0].id)
        assert job.provider_attempts == 3 and job.status == "failed" and job.result is None
    assert await labels(passport_db, agency, submissions) == {submissions[0].id: "ERROR"}


async def test_repeated_unexpected_worker_failures_have_finite_job_budget(passport_db):
    _, _, submissions = await seed(passport_db)
    await stage_all(passport_db, submissions)
    for _ in range(3):
        claim = await runtime._claim(submissions[0].id)
        assert claim is not None
        await runtime._release(claim)
        await mutate(
            passport_db,
            PassportEcrCheckModel,
            submissions[0].id,
            next_attempt_at=runtime._now() - timedelta(seconds=1),
        )
    assert await runtime._claim(submissions[0].id) is None
    async with passport_db() as session:
        job = await session.get(PassportEcrCheckModel, submissions[0].id)
        assert job.attempts == 3 and job.status == "failed" and job.provider_attempts == 0


async def test_same_key_overwrite_cannot_be_exported_as_na(passport_db, monkeypatch):
    agency, _, submissions = await seed(passport_db)
    await stage_all(passport_db, submissions)
    storage, _, _ = dependencies(monkeypatch, outcome="NA")
    first = storage.stat_file.return_value
    storage.stat_file.side_effect = [
        first,
        SimpleNamespace(size_bytes=first.size_bytes, checksum_sha256="0" * 64),
    ]
    await runtime.process_passport_checks()
    async with passport_db() as session:
        job = await session.get(PassportEcrCheckModel, submissions[0].id)
        assert job.reason == "source_changed" and job.result is None and job.status == "queued"
    assert await labels(passport_db, agency, submissions) == {submissions[0].id: "PENDING"}


async def test_repeated_redis_outage_does_not_exhaust_untouched_images(passport_db, monkeypatch):
    agency, _, submissions = await seed(passport_db, count=3)
    await stage_all(passport_db, submissions)

    async def unavailable():
        raise runtime.RateLimitUnavailable("synthetic Redis outage")

    _, pacer, calls = dependencies(monkeypatch, pacer_hook=unavailable)
    for _ in range(4):
        with pytest.raises(ExceptionGroup):
            await runtime.process_passport_checks()
        async with passport_db() as session:
            rows = list((await session.scalars(select(PassportEcrCheckModel))).all())
            for row in rows:
                assert row.status == "queued" and row.attempts == row.provider_attempts == 0
                row.next_attempt_at = runtime._now() - timedelta(seconds=1)
            await session.commit()
    assert calls.provider == 0
    pacer.acquire.side_effect = None
    assert await runtime.process_passport_checks() == 3
    assert calls.provider == 3
    assert set((await labels(passport_db, agency, submissions)).values()) == {"ECR"}


async def test_poison_classifier_failure_is_terminal_without_harming_neighbors(
    passport_db, monkeypatch
):
    _, _, submissions = await seed(passport_db, count=3)
    await stage_all(passport_db, submissions)

    async def one_poison(_classifier, calls):
        if calls.provider == 1:
            raise ValueError("synthetic malformed decoder result")

    _, _, calls = dependencies(monkeypatch, on_attempt=one_poison)
    assert await runtime.process_passport_checks() == 3
    assert calls.provider == 3
    async with passport_db() as session:
        rows = list((await session.scalars(select(PassportEcrCheckModel))).all())
        assert sum(row.status == "completed" and row.result == "ECR" for row in rows) == 2
        assert (
            sum(row.status == "failed" and row.reason == "processing_failed" for row in rows) == 1
        )
    assert await runtime.process_passport_checks() == 0


async def test_cancelled_admission_refunds_job_attempt_without_refunding_provider_slots(
    passport_db, monkeypatch
):
    _, _, submissions = await seed(passport_db)
    await stage_all(passport_db, submissions)
    claim = await runtime._claim(submissions[0].id)
    admitted = asyncio.Event()
    release_started = asyncio.Event()
    allow_release = asyncio.Event()
    original_release = runtime._release

    async def delayed_release(claim, **kwargs):
        release_started.set()
        await asyncio.wait_for(allow_release.wait(), timeout=5)
        await original_release(claim, **kwargs)

    monkeypatch.setattr(runtime, "_release", delayed_release)

    async def pending(_classifier, _calls):
        admitted.set()
        await asyncio.Event().wait()

    storage, pacer, _ = dependencies(monkeypatch, on_attempt=pending)
    task = asyncio.create_task(
        runtime._process_one(claim, storage=storage, client=Mock(), pacer=pacer)
    )
    await asyncio.wait_for(admitted.wait(), timeout=5)
    task.cancel()
    await asyncio.wait_for(release_started.wait(), timeout=5)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    allow_release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)
    async with passport_db() as session:
        job = await session.get(PassportEcrCheckModel, submissions[0].id)
        assert job.status == "queued" and job.attempts == 0 and job.provider_attempts == 1


async def test_staging_rolls_back_with_submission_transaction(passport_db):
    _, _, submissions = await seed(passport_db)
    async with passport_db() as session:
        assert await runtime.stage_passport_ecr_check(session, submissions[0].id)
        await session.rollback()
    async with passport_db() as session:
        assert await session.get(PassportEcrCheckModel, submissions[0].id) is None


async def test_active_lease_does_not_trigger_recovery_dispatch(passport_db, monkeypatch):
    _, _, submissions = await seed(passport_db)
    await stage_all(passport_db, submissions)
    await runtime._claim(submissions[0].id)
    dispatch = AsyncMock()
    monkeypatch.setattr(runtime, "dispatch_passport_ecr_checks", dispatch)
    assert await runtime.recover_passport_checks() == 0
    dispatch.assert_not_awaited()


async def test_recovery_backfills_in_bounded_pages_and_does_not_starve_eligible_groups(
    passport_db, monkeypatch
):
    # Invalid candidates precede valid groups; they must not occupy the first page.
    await seed(
        passport_db, config={"passport_ecr_enabled": True, "passport_enabled": False}, count=102
    )
    _, _, submissions = await seed(passport_db, count=105)
    dispatch = AsyncMock()
    monkeypatch.setattr(runtime, "dispatch_passport_ecr_checks", dispatch)
    assert await runtime.recover_passport_checks() == 100
    assert await runtime.recover_passport_checks() == 5
    assert await runtime.recover_passport_checks() == 0
    async with passport_db() as session:
        ids = set((await session.scalars(select(PassportEcrCheckModel.submission_id))).all())
        assert ids == {s.id for s in submissions}
    assert dispatch.await_count == 3


async def test_drain_is_bounded_to32_with_eight_lanes_and_resumes_remaining_jobs(
    passport_db, monkeypatch
):
    agency, _, submissions = await seed(passport_db, count=40)
    await stage_all(passport_db, submissions)
    barrier = asyncio.Event()

    async def overlap(_classifier, calls):
        if calls.active == 8:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), timeout=5)
        await asyncio.sleep(0.01)

    _, _, calls = dependencies(monkeypatch, on_attempt=overlap)
    assert await runtime.process_passport_checks() == 32
    assert calls.provider == 32 and calls.peak == 8
    async with passport_db() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PassportEcrCheckModel)
                .where(PassportEcrCheckModel.status == "queued")
            )
            == 8
        )
    assert await runtime.process_passport_checks() == 8
    assert set((await labels(passport_db, agency, submissions)).values()) == {"ECR"}
    assert await runtime.process_passport_checks() == 0


def test_passport_and_document_checks_share_queue_and_pacer():
    assert runtime.ProviderPacer is ProviderPacer
    assert celery_app.conf.task_routes[PASSPORT_ECR_TASK]["queue"] == ECR_QUEUE
    assert "app.infrastructure.ecr.passport_tasks" in celery_app.conf.include


def test_full_passport_drain_schedules_continuation_at_queue_tail(monkeypatch):
    from app.infrastructure.ecr import passport_tasks

    async def unused():
        return 32

    def run(coroutine):
        coroutine.close()
        return 32

    monkeypatch.setattr(passport_tasks, "process_passport_checks", unused)
    monkeypatch.setattr(passport_tasks.celery_async_runtime, "run", run)
    dispatch = Mock()
    monkeypatch.setattr(passport_tasks.celery_app, "send_task", dispatch)
    assert passport_tasks.process_passport_ecr_checks.run() == "processed=32"
    dispatch.assert_called_once_with(PASSPORT_ECR_TASK, queue=ECR_QUEUE)
