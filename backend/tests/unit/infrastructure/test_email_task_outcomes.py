"""Ordinary Celery outcomes and bounded storage reconciliation controls."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from app.infrastructure.email import storage_reconciliation
from app.infrastructure.email import tasks as email_tasks


def _complete(awaitable: object) -> None:
    awaitable.close()  # type: ignore[attr-defined]


def test_sync_task_forwards_the_complete_owner_generation_envelope(monkeypatch):
    captured = []

    async def sync(*args, **kwargs):
        captured.append((args, kwargs))

    def run(awaitable):
        import asyncio

        return asyncio.run(awaitable)

    monkeypatch.setattr(email_tasks, "run_connection_sync", sync)
    monkeypatch.setattr(email_tasks.celery_async_runtime, "run", run)
    connection_id, agency_id, owner_id = (uuid.uuid4() for _ in range(3))
    email_tasks.sync_email_connection.run(
        connection_id=connection_id,
        agency_id=agency_id,
        owner_user_id=owner_id,
        provider_account_id="synthetic-provider-account",
        sync_generation="4",
        provider_message_id="message-1",
    )
    assert captured == [
        (
            (connection_id,),
            dict(
                provider_message_id="message-1",
                agency_id=agency_id,
                owner_user_id=owner_id,
                provider_account_id="synthetic-provider-account",
                sync_generation=4,
            ),
        )
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("connection_id", "invalid"),
        ("agency_id", "invalid"),
        ("owner_user_id", None),
        ("sync_generation", None),
        ("sync_generation", "invalid"),
        ("sync_generation", -1),
        ("provider_account_id", None),
        ("provider_account_id", " "),
    ],
)
def test_sync_task_drops_invalid_envelopes_before_running(monkeypatch, field, value):
    runtime = Mock()
    monkeypatch.setattr(email_tasks.celery_async_runtime, "run", runtime)
    envelope = dict(
        connection_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        provider_account_id="account",
        sync_generation=1,
    )
    envelope[field] = value
    email_tasks.sync_email_connection.run(**envelope)
    runtime.assert_not_called()


@pytest.mark.parametrize("enabled,sync_enabled", [(False, True), (True, False)])
def test_disabled_dispatch_never_claims_or_publishes(monkeypatch, enabled, sync_enabled):
    runtime = Mock()
    monkeypatch.setattr(
        email_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            email_integrations_enabled=enabled, email_sync_enabled=sync_enabled
        ),
    )
    monkeypatch.setattr(email_tasks.celery_async_runtime, "run", runtime)
    assert email_tasks.dispatch_due_email_connections.run() == 0
    runtime.assert_not_called()


def test_dispatch_publishes_each_claimed_owner_generation(monkeypatch):
    envelope = email_tasks.EmailSyncTaskEnvelope(
        connection_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        provider_account_id="synthetic-account",
        sync_generation=4,
    )

    def run(awaitable):
        _complete(awaitable)
        return [envelope]

    publish = Mock()
    monkeypatch.setattr(
        email_tasks,
        "get_settings",
        lambda: SimpleNamespace(email_integrations_enabled=True, email_sync_enabled=True),
    )
    monkeypatch.setattr(email_tasks.celery_async_runtime, "run", run)
    monkeypatch.setattr(email_tasks.sync_email_connection, "apply_async", publish)
    assert email_tasks.dispatch_due_email_connections.run() == 1
    publish.assert_called_once_with(kwargs=envelope.task_kwargs(), queue="email_integrations")


def test_scheduler_heartbeat_closes_redis_even_when_write_fails(monkeypatch):
    client = Mock()
    client.setex.side_effect = RuntimeError("synthetic redis failure")
    monkeypatch.setattr(email_tasks.Redis, "from_url", lambda *args, **kwargs: client)
    email_tasks.record_email_scheduler_heartbeat.run()
    client.close.assert_called_once_with()


@pytest.mark.parametrize(
    "artifacts,documents,expected",
    [
        ([], [], ["orphan"]),
        (["orphan"], [], []),
        ([], ["orphan"], []),
    ],
)
async def test_storage_deletion_preserves_either_durable_reference(
    monkeypatch, artifacts, documents, expected
):
    results = []
    for keys in (artifacts, documents):
        result = MagicMock()
        result.scalars.return_value.all.return_value = keys
        results.append(result)
    session = AsyncMock()
    session.execute.side_effect = results
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    monkeypatch.setattr(storage_reconciliation, "AsyncSessionFactory", factory)
    storage = SimpleNamespace(delete_files=AsyncMock(return_value=1))
    count = await email_tasks._delete_unreferenced_email_storage_keys(
        storage=storage, candidate_keys=["orphan"]
    )
    assert session.execute.await_count == 2
    if expected:
        assert count == 1
        storage.delete_files.assert_awaited_once_with(expected)
    else:
        assert count == 0
        storage.delete_files.assert_not_awaited()


async def test_empty_storage_candidate_batch_does_not_open_database(monkeypatch):
    factory = Mock(side_effect=AssertionError("unexpected database access"))
    monkeypatch.setattr(storage_reconciliation, "AsyncSessionFactory", factory)
    assert (
        await email_tasks._delete_unreferenced_email_storage_keys(
            storage=SimpleNamespace(), candidate_keys=[]
        )
        == 0
    )
    factory.assert_not_called()


async def test_reconciliation_ignores_young_and_undated_objects(monkeypatch):
    now = datetime(2026, 10, 31, tzinfo=UTC)
    storage = SimpleNamespace(
        list_files=AsyncMock(
            side_effect=[
                [("email-integrations/new.pdf", now), ("email-integrations/unknown.pdf", None)],
                [],
            ]
        )
    )
    delete = AsyncMock()
    monkeypatch.setattr(
        storage_reconciliation,
        "get_settings",
        lambda: SimpleNamespace(email_storage_orphan_grace_hours=24),
    )
    monkeypatch.setattr(storage_reconciliation, "_delete_unreferenced_email_storage_keys", delete)
    assert await email_tasks._reconcile_orphaned_email_storage(storage=storage, now=now) == 0
    delete.assert_not_awaited()
