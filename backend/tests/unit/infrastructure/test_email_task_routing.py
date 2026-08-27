from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, call

import app.infrastructure.email.tasks as email_tasks
from app.infrastructure.email.ai_tasks import (
    EMAIL_AI_ANALYZE_TASK,
    EMAIL_AI_DEADLINE_SCAN_TASK,
    EMAIL_AI_DISPATCH_QUEUE,
    EMAIL_AI_DISPATCH_TASK,
    EMAIL_AI_QUEUE,
)
from app.infrastructure.email.tasks import (
    EMAIL_DISPATCH_TASK,
    EMAIL_INTEGRATION_QUEUE,
    EMAIL_RETENTION_TASK,
    EMAIL_SCHEDULER_HEARTBEAT_TASK,
    EMAIL_SYNC_TASK,
    EmailSyncTaskEnvelope,
    _apply_email_retention,
    _claim_due_dispatches,
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
    assert EMAIL_AI_QUEUE in queues
    assert queues[EMAIL_AI_QUEUE].durable is True
    assert routes[EMAIL_AI_ANALYZE_TASK]["queue"] == EMAIL_AI_QUEUE
    assert routes[EMAIL_AI_DISPATCH_TASK]["queue"] == EMAIL_AI_DISPATCH_QUEUE
    assert (
        routes[EMAIL_AI_DEADLINE_SCAN_TASK]["queue"]
        == EMAIL_AI_DISPATCH_QUEUE
    )


def test_email_dispatch_has_a_single_periodic_schedule() -> None:
    schedule = celery_app.conf.beat_schedule["dispatch-due-email-connections"]

    assert schedule["task"] == EMAIL_DISPATCH_TASK
    assert schedule["schedule"] == 5.0
    assert schedule["options"]["queue"] == EMAIL_INTEGRATION_QUEUE

    retention = celery_app.conf.beat_schedule["apply-email-content-retention"]
    assert retention["task"] == EMAIL_RETENTION_TASK
    assert retention["schedule"] == 86_400.0
    assert retention["options"]["queue"] == EMAIL_INTEGRATION_QUEUE

    heartbeat = celery_app.conf.beat_schedule["record-email-scheduler-heartbeat"]
    assert heartbeat["task"] == EMAIL_SCHEDULER_HEARTBEAT_TASK
    assert heartbeat["schedule"] == 60.0
    assert heartbeat["options"]["queue"] == EMAIL_INTEGRATION_QUEUE

    ai_dispatch = celery_app.conf.beat_schedule[
        "dispatch-travel-email-analyses"
    ]
    assert ai_dispatch["task"] == EMAIL_AI_DISPATCH_TASK
    assert ai_dispatch["schedule"] == 5.0
    assert ai_dispatch["options"]["queue"] == EMAIL_AI_DISPATCH_QUEUE

    deadline_scan = celery_app.conf.beat_schedule[
        "notify-travel-email-deadline-window"
    ]
    assert deadline_scan["task"] == EMAIL_AI_DEADLINE_SCAN_TASK
    assert deadline_scan["schedule"] == 60.0
    assert deadline_scan["options"]["queue"] == EMAIL_AI_DISPATCH_QUEUE


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

    email_tasks.sync_email_connection.run(
        connection_id=str(uuid.uuid4()),
        agency_id=str(uuid.uuid4()),
        owner_user_id=str(uuid.uuid4()),
        provider_account_id="provider-account",
        sync_generation=3,
    )


def test_sync_task_rejects_an_incomplete_owner_envelope(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = Mock()
    monkeypatch.setattr(email_tasks.celery_async_runtime, "run", runtime)

    email_tasks.sync_email_connection.run(connection_id=uuid.uuid4())
    email_tasks.sync_email_connection.run(
        connection_id=str(uuid.uuid4()),
        agency_id=str(uuid.uuid4()),
        owner_user_id="not-a-user-id",
        provider_account_id="provider-account",
        sync_generation=1,
    )

    runtime.assert_not_called()


def test_dispatch_task_logs_publish_failures_and_keeps_recovery_schedule(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    connection_id = uuid.uuid4()
    envelope = EmailSyncTaskEnvelope(
        connection_id=connection_id,
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        provider_account_id="provider-account",
        sync_generation=2,
    )

    def return_claimed_connection(
        awaitable: object,
    ) -> list[EmailSyncTaskEnvelope]:
        _close_awaitable(awaitable)
        return [envelope]

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
            redis=SimpleNamespace(broker_url="redis://broker.example.test/0"),
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


async def test_shorter_sync_interval_immediately_reschedules_healthy_idle_connections(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    connection = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        provider_account_id="provider-account",
        sync_generation=4,
        sync_state="idle",
        next_sync_at=None,
    )
    update_result = SimpleNamespace(rowcount=1)
    select_result = MagicMock()
    select_result.scalars.return_value.all.return_value = [connection]
    session = AsyncMock()
    session.execute.side_effect = [update_result, select_result]
    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value = session
    monkeypatch.setattr(email_tasks, "AsyncSessionFactory", session_factory)
    monkeypatch.setattr(
        email_tasks,
        "get_settings",
        lambda: SimpleNamespace(email_sync_interval_seconds=15),
    )

    claimed = await _claim_due_dispatches()

    assert claimed == [
        EmailSyncTaskEnvelope(
            connection_id=connection.id,
            agency_id=connection.agency_id,
            owner_user_id=connection.owner_user_id,
            provider_account_id=connection.provider_account_id,
            sync_generation=connection.sync_generation,
        )
    ]
    assert session.execute.await_count == 2
    assert connection.sync_state == "queued"
    assert connection.next_sync_at is not None
    session.commit.assert_awaited_once_with()


async def test_retention_scrubs_derived_ai_content_and_deletes_stale_drafts(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    artifact_result = MagicMock()
    artifact_result.scalars.return_value.all.return_value = []
    row_results = [
        SimpleNamespace(rowcount=count)
        for count in (2, 3, 5, 7, 11, 13, 17)
    ]
    oauth_result = SimpleNamespace(rowcount=0)
    session = AsyncMock()
    session.execute.side_effect = [artifact_result, *row_results, oauth_result]
    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value = session

    monkeypatch.setattr(email_tasks, "AsyncSessionFactory", session_factory)
    monkeypatch.setattr(
        email_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            email_content_retention_days=30,
            email_storage_orphan_grace_hours=24,
        ),
    )
    monkeypatch.setattr(
        email_tasks,
        "MinioStorageRepository",
        lambda: SimpleNamespace(delete_files=AsyncMock()),
    )
    reconcile = AsyncMock(return_value=17)
    monkeypatch.setattr(
        email_tasks,
        "_reconcile_orphaned_email_storage",
        reconcile,
    )

    retained_count = await _apply_email_retention()

    assert retained_count == 75
    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    assert any("UPDATE email_ai_analyses" in statement for statement in statements)
    assert any("UPDATE email_detected_deadlines" in statement for statement in statements)
    assert any("UPDATE email_action_proposals" in statement for statement in statements)
    assert any("DELETE FROM email_reply_drafts" in statement for statement in statements)
    assert any("UPDATE email_ai_feedback" in statement for statement in statements)
    assert any("UPDATE notifications" in statement for statement in statements)
    session.commit.assert_awaited_once_with()
    reconcile.assert_awaited_once()


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
