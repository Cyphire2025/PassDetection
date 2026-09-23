from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config.settings import Settings
from app.infrastructure.ai.gemini_ecr_service import EcrClassification
from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel
from app.infrastructure.ecr import ECR_BATCH_TASK, ECR_QUEUE, dispatch_ecr_batch, runtime
from app.infrastructure.processing.celery_app import celery_app


@pytest.fixture
async def ecr_db(monkeypatch, tmp_path):
    # File backing preserves the schema when cancelled heartbeat queries cause
    # SQLAlchemy to invalidate a connection, as production PostgreSQL does.
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'ecr.sqlite').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: EcrBatchModel.metadata.create_all(
                conn, tables=[EcrBatchModel.__table__, EcrItemModel.__table__]
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(runtime, "AsyncSessionFactory", factory)
    yield factory
    await engine.dispose()


async def make_batch(factory, *, count=3):
    batch = EcrBatchModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        title="ECR test",
        expected_count=count,
        status="queued",
    )
    items = [
        EcrItemModel(
            id=uuid.uuid4(),
            batch_id=batch.id,
            client_id=uuid.uuid4(),
            original_filename=f"passport-{i}.jpg",
            object_key=f"test/{i}.jpg",
            content_type="image/jpeg",
            sha256="0" * 64,
            status="queued",
        )
        for i in range(count)
    ]
    async with factory() as session:
        session.add(batch)
        session.add_all(items)
        await session.commit()
    return batch, items


async def test_claim_fences_stale_worker_and_recovers_only_interrupted_items(ecr_db):
    batch, items = await make_batch(ecr_db)
    store = runtime.BatchStore()
    first = await store.claim(batch.id)
    assert first is not None
    assert await store.claim(batch.id) is None
    completed = await store.next_item(batch.id, first)
    await store.save_result(
        batch.id,
        first,
        completed.id,
        EcrClassification("ECR", "phrase_present", "gemini-3.5-flash", 100, 10, 3, 2),
    )
    interrupted = await store.next_item(batch.id, first)
    async with ecr_db() as session:
        current = await session.get(EcrBatchModel, batch.id)
        current.lease_expires_at = runtime._now() - timedelta(seconds=1)
        await session.commit()
    replacement = await store.claim(batch.id)
    assert replacement is not None and replacement != first
    with pytest.raises(runtime.LeaseLost):
        await store.fail_item(batch.id, first, interrupted.id, "old_worker_result")
    await store.release(batch.id, first)
    async with ecr_db() as session:
        current = await session.get(EcrBatchModel, batch.id)
        finished = await session.get(EcrItemModel, completed.id)
        unfinished = await session.get(EcrItemModel, interrupted.id)
        assert current.lease_token == replacement
        assert finished.status == "completed" and finished.result == "ECR"
        assert finished.input_tokens == 100 and finished.output_tokens == 13
        assert finished.attempts == 2
        assert unfinished.status == "queued" and unfinished.result is None


async def test_review_and_provider_failure_cannot_become_na(ecr_db):
    batch, _ = await make_batch(ecr_db, count=2)
    store = runtime.BatchStore()
    token = await store.claim(batch.id)
    first = await store.next_item(batch.id, token)
    await store.save_result(batch.id, token, first.id, EcrClassification("REVIEW", "blur", "test"))
    second = await store.next_item(batch.id, token)
    await store.save_result(
        batch.id, token, second.id, EcrClassification("ERROR", "unavailable", "test")
    )
    await store.finish(batch.id, token)
    async with ecr_db() as session:
        current = await session.get(EcrBatchModel, batch.id)
        rows = list((await session.scalars(select(EcrItemModel))).all())
        assert current.status == "completed_with_errors"
        assert current.lease_token is None
        assert {(row.status, row.result) for row in rows} == {
            ("completed", "NEEDS_REVIEW"),
            ("failed", None),
        }


async def test_release_requeues_interrupted_rows_and_keeps_completed_results(ecr_db):
    batch, _ = await make_batch(ecr_db, count=2)
    store = runtime.BatchStore()
    token = await store.claim(batch.id)
    first = await store.next_item(batch.id, token)
    await store.save_result(batch.id, token, first.id, EcrClassification("NA", "absent", "test"))
    second = await store.next_item(batch.id, token)
    await store.release(batch.id, token)
    async with ecr_db() as session:
        current = await session.get(EcrBatchModel, batch.id)
        assert current.status == "queued"
        assert (await session.get(EcrItemModel, first.id)).result == "NA"
        assert (await session.get(EcrItemModel, second.id)).status == "queued"


def fake_lane_dependencies(count=20):
    data = b"canonical jpeg fixture"
    pending = deque(runtime.WorkItem(uuid.uuid4(), f"ecr/{i}", "image/jpeg") for i in range(count))

    async def next_item(*args):
        return pending.popleft() if pending else None

    store = SimpleNamespace(
        next_item=next_item, save_result=AsyncMock(), fail_item=AsyncMock(), renew=AsyncMock()
    )
    storage = SimpleNamespace(
        stat_file=AsyncMock(
            return_value=SimpleNamespace(
                size_bytes=len(data),
                checksum_sha256=hashlib.sha256(data).hexdigest(),
            )
        ),
        get_file_range=AsyncMock(return_value=data),
    )
    return store, storage


async def test_lanes_process_multiple_images_concurrently_with_strict_bound():
    store, storage = fake_lane_dependencies(24)
    active = 0
    peak = 0

    async def classify(*args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.001)
        active -= 1
        return EcrClassification("ECR", "present", "test")

    await runtime._run_lanes(
        uuid.uuid4(),
        uuid.uuid4(),
        store=store,
        storage=storage,
        classifier=SimpleNamespace(classify=classify),
        concurrency=8,
        max_image_bytes=1024,
    )
    assert peak == 8
    assert store.save_result.await_count == 24
    store.fail_item.assert_not_awaited()


async def test_heartbeat_failure_cancels_all_active_provider_lanes(monkeypatch):
    store, storage = fake_lane_dependencies(8)
    store.renew.side_effect = runtime.LeaseLost("stale")
    monkeypatch.setattr(runtime, "HEARTBEAT_SECONDS", 0.01)
    cancelled = 0

    async def classify(*args):
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled += 1
            raise

    with pytest.raises(ExceptionGroup) as failure:
        await runtime._run_lanes(
            uuid.uuid4(),
            uuid.uuid4(),
            store=store,
            storage=storage,
            classifier=SimpleNamespace(classify=classify),
            concurrency=8,
            max_image_bytes=1024,
        )
    assert any(isinstance(exc, runtime.LeaseLost) for exc in failure.value.exceptions)
    assert cancelled == 8
    store.save_result.assert_not_awaited()


async def test_oversized_or_corrupted_storage_never_reaches_gemini():
    store, storage = fake_lane_dependencies(2)
    storage.stat_file.side_effect = [
        SimpleNamespace(size_bytes=5000, checksum_sha256=None),
        SimpleNamespace(size_bytes=22, checksum_sha256="0" * 64),
    ]
    classify = AsyncMock()
    await runtime._run_lanes(
        uuid.uuid4(),
        uuid.uuid4(),
        store=store,
        storage=storage,
        classifier=SimpleNamespace(classify=classify),
        concurrency=1,
        max_image_bytes=1024,
    )
    classify.assert_not_awaited()
    assert [call.args[-1] for call in store.fail_item.await_args_list] == [
        "image_too_large",
        "image_integrity_failed",
    ]


async def test_pacer_waits_for_shared_permission_and_fails_closed(monkeypatch):
    redis = SimpleNamespace(eval=AsyncMock(side_effect=[500, 0]))
    sleep = AsyncMock()
    monkeypatch.setattr(runtime.asyncio, "sleep", sleep)
    pacer = runtime.ProviderPacer(redis, 120)
    await pacer.acquire()
    sleep.assert_awaited_once_with(0.5)
    assert redis.eval.await_count == 2
    assert redis.eval.call_args.args[-1] == 500
    redis.eval.side_effect = ConnectionError("unavailable")
    with pytest.raises(runtime.RateLimitUnavailable):
        await pacer.acquire()


def test_ecr_defaults_allow_120_attempts_per_minute_with_eight_lanes(monkeypatch):
    monkeypatch.delenv("ECR_REQUESTS_PER_MINUTE", raising=False)
    monkeypatch.delenv("ECR_MAX_CONCURRENCY", raising=False)
    settings = Settings(app_secret_key="unit-test-only", _env_file=None)
    assert settings.ecr_requests_per_minute == 120
    assert settings.ecr_max_concurrency == 8


@pytest.mark.parametrize("requests_per_minute", [0, -1])
def test_ecr_pacing_rejects_nonpositive_requests_per_minute(requests_per_minute):
    with pytest.raises(ValidationError, match="ecr_requests_per_minute"):
        Settings(
            app_secret_key="unit-test-only",
            ecr_requests_per_minute=requests_per_minute,
            _env_file=None,
        )


@pytest.fixture
def batch_runtime_dependencies(monkeypatch):
    token = uuid.uuid4()
    store = SimpleNamespace(
        claim=AsyncMock(return_value=token), finish=AsyncMock(), release=AsyncMock()
    )
    settings = SimpleNamespace(
        redis=SimpleNamespace(broker_url="redis://unused:6379/0"),
        ecr_requests_per_minute=120,
        ecr_max_concurrency=8,
        ecr_image_max_bytes=1024,
    )
    client = SimpleNamespace(aclose=AsyncMock())

    @asynccontextmanager
    async def client_context():
        try:
            yield client
        finally:
            await client.aclose()

    dependencies = SimpleNamespace(
        token=token,
        store=store,
        settings=settings,
        client=client,
        classifier=Mock(),
        storage=Mock(),
        lanes=AsyncMock(),
        redis=SimpleNamespace(eval=AsyncMock(return_value=0), aclose=AsyncMock()),
    )
    dependencies.redis_factory = Mock(return_value=dependencies.redis)
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "BatchStore", lambda: store)
    monkeypatch.setattr(runtime.httpx, "AsyncClient", client_context)
    monkeypatch.setattr(runtime, "GeminiEcrService", dependencies.classifier)
    monkeypatch.setattr(runtime, "MinioStorageRepository", lambda: dependencies.storage)
    monkeypatch.setattr(runtime, "_run_lanes", dependencies.lanes)
    monkeypatch.setattr(runtime.Redis, "from_url", dependencies.redis_factory)
    return dependencies


async def test_batch_uses_eight_lanes_and_paces_every_attempt_including_retries(
    batch_runtime_dependencies, monkeypatch
):
    dependencies = batch_runtime_dependencies
    # One image's initial attempt and two retries must all acquire admission.
    dependencies.redis.eval.side_effect = [0, 500, 0, 500, 0]
    sleep = AsyncMock()
    monkeypatch.setattr(runtime.asyncio, "sleep", sleep)
    batch_id = uuid.uuid4()

    async def run_lanes(*args, **kwargs):
        acquire = dependencies.classifier.call_args.kwargs["before_attempt"]
        assert acquire is not None
        for _ in range(3):
            await acquire()
        dependencies.redis.aclose.assert_not_awaited()
        dependencies.client.aclose.assert_not_awaited()

    dependencies.lanes.side_effect = run_lanes
    assert await runtime.process_batch(batch_id) == "completed"

    dependencies.redis_factory.assert_called_once()
    assert dependencies.redis.eval.await_count == 5
    assert all(call.args[-1] == 500 for call in dependencies.redis.eval.await_args_list)
    assert [call.args for call in sleep.await_args_list] == [(0.5,), (0.5,)]
    dependencies.classifier.assert_called_once()
    assert dependencies.classifier.call_args.kwargs["settings"] is dependencies.settings
    assert dependencies.classifier.call_args.kwargs["http_client"] is dependencies.client
    dependencies.lanes.assert_awaited_once_with(
        batch_id,
        dependencies.token,
        store=dependencies.store,
        storage=dependencies.storage,
        classifier=dependencies.classifier.return_value,
        concurrency=8,
        max_image_bytes=1024,
    )
    dependencies.redis.aclose.assert_awaited_once_with()
    dependencies.client.aclose.assert_awaited_once_with()
    dependencies.store.finish.assert_awaited_once_with(batch_id, dependencies.token)
    dependencies.store.release.assert_not_awaited()


@pytest.mark.parametrize("failure", [RuntimeError("storage unavailable"), asyncio.CancelledError()])
async def test_batch_failure_releases_lease_and_closes_clients(batch_runtime_dependencies, failure):
    dependencies = batch_runtime_dependencies
    dependencies.lanes.side_effect = failure
    batch_id = uuid.uuid4()

    with pytest.raises(type(failure)):
        await runtime.process_batch(batch_id)

    dependencies.store.release.assert_awaited_once_with(batch_id, dependencies.token)
    dependencies.store.finish.assert_not_awaited()
    dependencies.redis_factory.assert_called_once()
    dependencies.redis.aclose.assert_awaited_once_with()
    dependencies.client.aclose.assert_awaited_once_with()


def test_ecr_jobs_have_isolated_queue_long_envelope_and_recovery_schedule():
    assert celery_app.conf.task_routes[ECR_BATCH_TASK] == {"queue": ECR_QUEUE}
    assert celery_app.conf.task_annotations[ECR_BATCH_TASK]["time_limit"] == 3600
    assert celery_app.conf.beat_schedule["recover-ecr-batches"]["schedule"] == 60
    assert "app.infrastructure.ecr.tasks" in celery_app.conf.include


async def test_retention_deletes_only_old_owned_objects_and_preserves_results(ecr_db, monkeypatch):
    batch, items = await make_batch(ecr_db, count=3)
    old = runtime._now() - timedelta(days=8)
    async with ecr_db() as session:
        current = await session.get(EcrBatchModel, batch.id)
        current.status = "completed"
        current.created_at = old
        for index, item in enumerate(items):
            row = await session.get(EcrItemModel, item.id)
            row.created_at = old
            row.status = "completed"
            row.result = "ECR"
            row.object_key = (
                f"ecr-checks/{batch.agency_id}/{batch.id}/{item.id}.jpg"
                if index < 2
                else "passports/unrelated.jpg"
            )
        await session.commit()
    storage = SimpleNamespace(delete_files=AsyncMock())
    monkeypatch.setattr(runtime, "MinioStorageRepository", lambda: storage)
    monkeypatch.setattr(runtime, "_remove_orphan_images", AsyncMock(return_value=0))
    assert await runtime.apply_retention() == 2
    deleted = storage.delete_files.call_args.args[0]
    assert len(deleted) == 2 and all(key.startswith("ecr-checks/") for key in deleted)
    async with ecr_db() as session:
        rows = list((await session.scalars(select(EcrItemModel))).all())
        assert all(row.result == "ECR" for row in rows)
        assert sum(row.object_key is None for row in rows) == 2
        assert any(row.object_key == "passports/unrelated.jpg" for row in rows)


async def test_dispatch_broker_failure_is_visible_to_the_caller(monkeypatch):
    send = Mock(side_effect=ConnectionError("broker unavailable"))
    monkeypatch.setattr(celery_app, "send_task", send)
    batch_id = uuid.uuid4()
    with pytest.raises(ConnectionError):
        await dispatch_ecr_batch(batch_id)
    send.assert_called_once_with(ECR_BATCH_TASK, args=[str(batch_id)], queue=ECR_QUEUE, retry=False)


async def test_recovery_finds_queued_and_expired_but_skips_live_and_finished(ecr_db, monkeypatch):
    queued, _ = await make_batch(ecr_db, count=1)
    stale, _ = await make_batch(ecr_db, count=1)
    live, _ = await make_batch(ecr_db, count=1)
    finished, _ = await make_batch(ecr_db, count=1)
    async with ecr_db() as session:
        (await session.get(EcrBatchModel, queued.id)).updated_at = runtime._now() - timedelta(
            minutes=1
        )
        stale_row = await session.get(EcrBatchModel, stale.id)
        stale_row.status = "processing"
        stale_row.lease_expires_at = runtime._now() - timedelta(seconds=1)
        live_row = await session.get(EcrBatchModel, live.id)
        live_row.status = "processing"
        live_row.lease_expires_at = runtime._now() + timedelta(seconds=90)
        (await session.get(EcrBatchModel, finished.id)).status = "completed"
        await session.commit()
    dispatch = AsyncMock()
    monkeypatch.setattr(runtime, "dispatch_ecr_batch", dispatch)
    assert await runtime.recover_batches() == 2
    assert {call.args[0] for call in dispatch.await_args_list} == {queued.id, stale.id}


async def test_orphan_sweep_keeps_live_references_recent_images_and_other_namespaces(
    ecr_db, monkeypatch
):
    batch, items = await make_batch(ecr_db, count=1)
    referenced = f"ecr-checks/{batch.agency_id}/{batch.id}/{items[0].id}.jpg"
    orphan = f"ecr-checks/{batch.agency_id}/{batch.id}/{uuid.uuid4()}.jpg"
    fresh = f"ecr-checks/{batch.agency_id}/{batch.id}/{uuid.uuid4()}.jpg"
    async with ecr_db() as session:
        (await session.get(EcrItemModel, items[0].id)).object_key = referenced
        await session.commit()
    now = runtime._now()
    old = now - timedelta(days=8)
    storage = SimpleNamespace(
        list_files=AsyncMock(
            return_value=[
                (referenced, old),
                (orphan, old),
                (fresh, now),
                ("passports/other.jpg", old),
            ]
        ),
        delete_files=AsyncMock(return_value=1),
    )
    redis = SimpleNamespace(
        get=AsyncMock(return_value=None), delete=AsyncMock(), aclose=AsyncMock()
    )
    monkeypatch.setattr(runtime.Redis, "from_url", lambda *args, **kwargs: redis)
    assert await runtime._remove_orphan_images(storage, now - timedelta(days=7)) == 1
    storage.delete_files.assert_awaited_once_with([orphan])
    redis.aclose.assert_awaited_once_with()


async def test_thousand_image_batch_persists_every_duplicate_filename_with_eight_lanes(
    ecr_db, monkeypatch
):
    """Exercise the complete runtime with 1000 real persisted item rows.

    SQLite ignores SELECT FOR UPDATE. Serialize transaction contexts here to
    emulate the single batch row's PostgreSQL transaction lock, while provider
    requests run concurrently. This tests durable orchestration and accounting,
    not PostgreSQL lock behavior or real provider throughput.
    """
    settings = SimpleNamespace(
        redis=SimpleNamespace(broker_url="redis://unused:6379/0"),
        ecr_requests_per_minute=120,
        ecr_max_concurrency=8,
        ecr_image_max_bytes=1024,
    )
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    batch, items = await make_batch(ecr_db, count=1000)
    async with ecr_db() as session:
        for row in (await session.scalars(select(EcrItemModel))).all():
            row.original_filename = "passport-back.jpg"
        await session.commit()
    db_lock = asyncio.Lock()

    @asynccontextmanager
    async def serialized_sessions():
        async with db_lock:
            async with ecr_db() as session:
                yield session

    monkeypatch.setattr(runtime, "AsyncSessionFactory", serialized_sessions)
    content_by_key = {item.object_key: str(index).encode() for index, item in enumerate(items)}

    async def stat_file(key):
        data = content_by_key[key]
        return SimpleNamespace(
            size_bytes=len(data), checksum_sha256=hashlib.sha256(data).hexdigest()
        )

    async def get_file_range(key, *, start, end):
        data = content_by_key[key]
        assert start == 0 and end == len(data) - 1
        return data

    storage = SimpleNamespace(stat_file=stat_file, get_file_range=get_file_range)
    monkeypatch.setattr(runtime, "MinioStorageRepository", lambda: storage)
    redis = SimpleNamespace(eval=AsyncMock(return_value=0), aclose=AsyncMock())
    monkeypatch.setattr(runtime.Redis, "from_url", lambda *args, **kwargs: redis)
    initial_wave = asyncio.Event()
    active = peak = calls = 0

    class FakeClassifier:
        def __init__(self, *, before_attempt, **kwargs):
            self.before_attempt = before_attempt

        async def classify(self, content, content_type):
            nonlocal active, peak, calls
            await self.before_attempt()
            assert content_type == "image/jpeg"
            active += 1
            calls += 1
            peak = max(peak, active)
            if active == 8:
                initial_wave.set()
            try:
                await asyncio.wait_for(initial_wave.wait(), timeout=5)
                await asyncio.sleep(0)
                result = ("ECR", "NA", "REVIEW")[int(content) % 3]
                return EcrClassification(result, "test_classification", "test-model", 150, 10, 0, 1)
            finally:
                active -= 1

    monkeypatch.setattr(runtime, "GeminiEcrService", FakeClassifier)
    monkeypatch.setattr(runtime, "HEARTBEAT_SECONDS", 0.05)
    assert await asyncio.wait_for(runtime.process_batch(batch.id), timeout=60) == "completed"
    async with ecr_db() as session:
        persisted = list((await session.scalars(select(EcrItemModel))).all())
        finished = await session.get(EcrBatchModel, batch.id)
        assert len(persisted) == 1000
        assert {row.id for row in persisted} == {item.id for item in items}
        assert all(row.original_filename == "passport-back.jpg" for row in persisted)
        assert all(row.status == "completed" and row.attempts == 1 for row in persisted)
        assert sum(row.result == "ECR" for row in persisted) == 334
        assert sum(row.result == "NA" for row in persisted) == 333
        assert sum(row.result == "NEEDS_REVIEW" for row in persisted) == 333
        assert sum(row.input_tokens for row in persisted) == 150_000
        assert sum(row.output_tokens for row in persisted) == 10_000
        assert finished.status == "completed"
        assert finished.lease_token is None and finished.lease_expires_at is None
    assert peak == 8 and calls == 1000 and active == 0
    assert redis.eval.await_count == 1000
    redis.aclose.assert_awaited_once_with()


async def test_retention_skips_five_hundred_older_batches_with_no_remaining_images(
    ecr_db, monkeypatch
):
    old = runtime._now() - timedelta(days=10)
    agency_id = uuid.uuid4()
    batches = [
        EcrBatchModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            title="Old batch",
            expected_count=1,
            status="completed",
            created_at=old + timedelta(seconds=index),
        )
        for index in range(501)
    ]
    live_key = f"ecr-checks/{agency_id}/{batches[-1].id}/{uuid.uuid4()}.jpg"
    async with ecr_db() as session:
        session.add_all(batches)
        session.add_all(
            [
                EcrItemModel(
                    id=uuid.uuid4(),
                    batch_id=batch.id,
                    client_id=uuid.uuid4(),
                    original_filename="passport.jpg",
                    content_type="image/jpeg",
                    sha256="0" * 64,
                    status="completed",
                    result="NA",
                    created_at=old,
                    object_key=live_key if index == 500 else None,
                )
                for index, batch in enumerate(batches)
            ]
        )
        await session.commit()
    storage = SimpleNamespace(delete_files=AsyncMock())
    monkeypatch.setattr(runtime, "MinioStorageRepository", lambda: storage)
    monkeypatch.setattr(runtime, "_remove_orphan_images", AsyncMock(return_value=0))
    assert await runtime.apply_retention() == 1
    storage.delete_files.assert_awaited_once_with([live_key])
    async with ecr_db() as session:
        assert not list(
            (
                await session.scalars(
                    select(EcrItemModel.id).where(EcrItemModel.object_key.is_not(None))
                )
            ).all()
        )
