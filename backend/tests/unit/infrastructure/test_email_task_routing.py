from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import app.infrastructure.email.tasks as email_tasks
from app.infrastructure.email.tasks import (
    EMAIL_DISPATCH_TASK,
    EMAIL_INTEGRATION_QUEUE,
    EMAIL_RETENTION_TASK,
    EMAIL_SCHEDULER_HEARTBEAT_TASK,
    EMAIL_SYNC_TASK,
    _reconcile_orphaned_email_storage,
    _storage_object_is_older_than,
)
from app.infrastructure.processing.celery_app import celery_app


def test_email_tasks_use_a_dedicated_durable_queue() -> None:
    queues = {queue.name: queue for queue in celery_app.conf.task_queues}
    routes = celery_app.conf.task_routes

    assert EMAIL_INTEGRATION_QUEUE in queues
    assert queues[EMAIL_INTEGRATION_QUEUE].durable is True
    assert routes[EMAIL_SYNC_TASK]["queue"] == EMAIL_INTEGRATION_QUEUE
    assert routes[EMAIL_DISPATCH_TASK]["queue"] == EMAIL_INTEGRATION_QUEUE
    assert routes[EMAIL_RETENTION_TASK]["queue"] == EMAIL_INTEGRATION_QUEUE
    assert routes[EMAIL_SCHEDULER_HEARTBEAT_TASK]["queue"] == EMAIL_INTEGRATION_QUEUE


def test_email_dispatch_has_a_single_periodic_schedule() -> None:
    schedule = celery_app.conf.beat_schedule["dispatch-due-email-connections"]

    assert schedule["task"] == EMAIL_DISPATCH_TASK
    assert schedule["schedule"] == 60.0
    assert schedule["options"]["queue"] == EMAIL_INTEGRATION_QUEUE

    retention = celery_app.conf.beat_schedule["apply-email-content-retention"]
    assert retention["task"] == EMAIL_RETENTION_TASK
    assert retention["schedule"] == 86_400.0
    assert retention["options"]["queue"] == EMAIL_INTEGRATION_QUEUE

    heartbeat = celery_app.conf.beat_schedule["record-email-scheduler-heartbeat"]
    assert heartbeat["task"] == EMAIL_SCHEDULER_HEARTBEAT_TASK
    assert heartbeat["schedule"] == 60.0
    assert heartbeat["options"]["queue"] == EMAIL_INTEGRATION_QUEUE


def _close_awaitable(awaitable: object) -> None:
    close = getattr(awaitable, "close", None)
    if callable(close):
        close()


def test_sync_task_logs_runtime_failures_without_masking_them(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    def fail_runtime(awaitable: object) -> None:
        _close_awaitable(awaitable)
        raise RuntimeError("simulated runtime failure")

    monkeypatch.setattr(email_tasks.celery_async_runtime, "run", fail_runtime)

    email_tasks.sync_email_connection.run(connection_id=str(uuid.uuid4()))


def test_dispatch_task_logs_publish_failures_and_keeps_recovery_schedule(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    connection_id = uuid.uuid4()

    def return_claimed_connection(awaitable: object) -> list[uuid.UUID]:
        _close_awaitable(awaitable)
        return [connection_id]

    def fail_publish(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("simulated broker failure")

    monkeypatch.setattr(
        email_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            email_integrations_enabled=True,
            email_sync_enabled=True,
        ),
    )
    monkeypatch.setattr(
        email_tasks.celery_async_runtime,
        "run",
        return_claimed_connection,
    )
    monkeypatch.setattr(email_tasks.sync_email_connection, "apply_async", fail_publish)

    assert email_tasks.dispatch_due_email_connections.run() == 0


def test_retention_task_logs_runtime_failures_without_masking_them(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    def fail_runtime(awaitable: object) -> None:
        _close_awaitable(awaitable)
        raise RuntimeError("simulated retention failure")

    monkeypatch.setattr(email_tasks.celery_async_runtime, "run", fail_runtime)

    assert email_tasks.apply_email_retention.run() == 0


def test_scheduler_heartbeat_is_written_with_a_short_ttl(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = Mock()
    monkeypatch.setattr(
        email_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis=SimpleNamespace(url="redis://example.test/0"),
            processing_worker_ping_timeout_seconds=1.0,
        ),
    )
    monkeypatch.setattr(
        email_tasks.Redis,
        "from_url",
        lambda *args, **kwargs: client,
    )

    email_tasks.record_email_scheduler_heartbeat.run()

    assert client.setex.call_args.args[1] == 180
    client.close.assert_called_once_with()


def test_orphan_reconciliation_waits_for_the_storage_grace_period() -> None:
    cutoff = datetime(2026, 7, 28, 12, tzinfo=UTC)

    assert _storage_object_is_older_than(cutoff, cutoff=cutoff)
    assert _storage_object_is_older_than(
        (cutoff - timedelta(seconds=1)).replace(tzinfo=None),
        cutoff=cutoff,
    )
    assert not _storage_object_is_older_than(
        cutoff + timedelta(seconds=1),
        cutoff=cutoff,
    )
    assert not _storage_object_is_older_than(None, cutoff=cutoff)


async def test_orphan_reconciliation_advances_through_every_storage_page(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2026, 7, 28, 12, tzinfo=UTC)
    old = now - timedelta(days=2)
    storage = SimpleNamespace(
        list_files=AsyncMock(
            side_effect=[
                [
                    ("email-integrations/a/one.pdf", old),
                    ("email-integrations/a/two.pdf", old),
                ],
                [("email-integrations/z/three.pdf", old)],
                [],
            ]
        )
    )
    deleted_batches: list[list[str]] = []

    async def delete_candidates(*, storage, candidate_keys):  # type: ignore[no-untyped-def]
        del storage
        deleted_batches.append(candidate_keys)
        return len(candidate_keys)

    monkeypatch.setattr(
        email_tasks,
        "get_settings",
        lambda: SimpleNamespace(email_storage_orphan_grace_hours=24),
    )
    monkeypatch.setattr(email_tasks, "_EMAIL_STORAGE_RECONCILE_PAGE_SIZE", 2)
    monkeypatch.setattr(
        email_tasks,
        "_delete_unreferenced_email_storage_keys",
        delete_candidates,
    )

    assert (
        await _reconcile_orphaned_email_storage(
            storage=storage,  # type: ignore[arg-type]
            now=now,
        )
        == 3
    )
    assert storage.list_files.await_args_list == [
        call(prefix="email-integrations/", limit=2, start_after=None),
        call(
            prefix="email-integrations/",
            limit=2,
            start_after="email-integrations/a/two.pdf",
        ),
        call(
            prefix="email-integrations-canonical/",
            limit=2,
            start_after=None,
        ),
    ]
    assert deleted_batches == [
        [
            "email-integrations/a/one.pdf",
            "email-integrations/a/two.pdf",
        ],
        ["email-integrations/z/three.pdf"],
    ]
