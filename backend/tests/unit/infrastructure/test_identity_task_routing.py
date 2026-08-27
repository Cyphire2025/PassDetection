from __future__ import annotations

from collections.abc import Coroutine
from typing import Protocol, cast

import pytest

from app.infrastructure.processing.celery_app import (
    IDENTITY_RECOVERY_DELIVERY_TASK,
    IDENTITY_RETENTION_TASK,
    celery_app,
)
from app.infrastructure.security import identity_tasks
from app.infrastructure.security.identity_retention import IdentityRetentionResult


class _RunnableTask(Protocol):
    def run(self) -> object: ...


def test_identity_delivery_and_retention_have_durable_periodic_routes() -> None:
    routes = celery_app.conf.task_routes
    delivery = celery_app.conf.beat_schedule["deliver-password-recovery-notifications"]
    retention = celery_app.conf.beat_schedule["apply-identity-record-retention"]

    assert routes[IDENTITY_RECOVERY_DELIVERY_TASK]["queue"] == "passport_ocr"
    assert routes[IDENTITY_RETENTION_TASK]["queue"] == "passport_ocr"
    assert delivery == {
        "task": IDENTITY_RECOVERY_DELIVERY_TASK,
        "schedule": 10.0,
        "options": {"queue": "passport_ocr"},
    }
    assert retention == {
        "task": IDENTITY_RETENTION_TASK,
        "schedule": 86_400.0,
        "options": {"queue": "passport_ocr"},
    }
    assert "app.infrastructure.security.identity_tasks" in celery_app.conf.include


def _close_coroutine(awaitable: object) -> None:
    cast(Coroutine[object, object, object], awaitable).close()


def test_delivery_task_returns_the_durable_delivery_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(awaitable: object) -> int:
        _close_coroutine(awaitable)
        return 7

    monkeypatch.setattr(identity_tasks.celery_async_runtime, "run", run)

    assert identity_tasks.deliver_recovery_notifications.run() == 7


def test_retention_task_returns_each_bounded_cleanup_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = IdentityRetentionResult(
        action_tokens=2,
        auth_challenges=3,
        recovery_codes=5,
        notification_outbox=7,
    )

    def run(awaitable: object) -> IdentityRetentionResult:
        _close_coroutine(awaitable)
        return result

    monkeypatch.setattr(identity_tasks.celery_async_runtime, "run", run)

    assert identity_tasks.apply_identity_record_retention.run() == {
        "action_tokens": 2,
        "auth_challenges": 3,
        "recovery_codes": 5,
        "notification_outbox": 7,
        "total": 17,
    }


@pytest.mark.parametrize(
    "task",
    [
        identity_tasks.deliver_recovery_notifications,
        identity_tasks.apply_identity_record_retention,
    ],
)
def test_identity_tasks_surface_failures_for_celery_retry_and_observability(
    monkeypatch: pytest.MonkeyPatch,
    task: object,
) -> None:
    def fail(awaitable: object) -> object:
        _close_coroutine(awaitable)
        raise RuntimeError("injected task failure")

    monkeypatch.setattr(identity_tasks.celery_async_runtime, "run", fail)

    with pytest.raises(RuntimeError, match="injected task failure"):
        cast(_RunnableTask, task).run()
