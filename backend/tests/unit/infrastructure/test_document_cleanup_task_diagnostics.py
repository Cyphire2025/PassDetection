"""The unchanged Celery task boundary exposes aggregates and exception types."""

from __future__ import annotations

import pytest

from app.infrastructure.documents import cleanup_tasks


@pytest.mark.parametrize("operation", ["tombstones", "orphans"])
def test_cleanup_task_failures_do_not_log_private_provider_details(monkeypatch, operation):
    marker = object()
    target = (
        "process_due_storage_cleanup_jobs"
        if operation == "tombstones"
        else "_reconcile_document_storage_orphans"
    )
    monkeypatch.setattr(cleanup_tasks, target, lambda: marker)
    records = []
    monkeypatch.setattr(cleanup_tasks.logger, "error", lambda *args: records.append(args))

    def fail(awaitable):
        assert awaitable is marker
        raise RuntimeError("synthetic private image key and credentials")

    monkeypatch.setattr(cleanup_tasks.celery_async_runtime, "run", fail)
    task = (
        cleanup_tasks.cleanup_document_storage
        if operation == "tombstones"
        else cleanup_tasks.reconcile_document_storage_orphans
    )
    with pytest.raises(RuntimeError, match="synthetic private"):
        task.run()
    assert len(records) == 1
    assert records[0][1] == "RuntimeError"
    assert "synthetic private" not in str(records)


def test_tombstone_task_returns_the_existing_aggregate_count(monkeypatch):
    marker = object()
    monkeypatch.setattr(cleanup_tasks, "process_due_storage_cleanup_jobs", lambda: marker)

    def run(awaitable):
        assert awaitable is marker
        return 7

    monkeypatch.setattr(cleanup_tasks.celery_async_runtime, "run", run)
    assert cleanup_tasks.cleanup_document_storage.run() == 7
