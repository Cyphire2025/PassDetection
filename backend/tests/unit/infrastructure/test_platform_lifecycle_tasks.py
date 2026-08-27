from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.infrastructure import platform_lifecycle_tasks
from app.infrastructure.processing.celery_app import celery_app


class _SessionContext:
    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        del exc_type, exc, traceback


async def test_lifecycle_task_applies_operational_retention_in_same_transaction() -> None:
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    lifecycle = SimpleNamespace(as_dict=lambda: {"deleted_passports": 2})
    operational = SimpleNamespace(
        as_dict=lambda: {
            "expired_runtimes": 3,
            "deleted_discard_tombstones": 4,
        }
    )

    with (
        patch.object(
            platform_lifecycle_tasks,
            "AsyncSessionFactory",
            return_value=_SessionContext(session),
        ),
        patch.object(
            platform_lifecycle_tasks,
            "apply_platform_lifecycle_policies",
            new=AsyncMock(return_value=lifecycle),
        ) as apply_lifecycle,
        patch.object(
            platform_lifecycle_tasks,
            "apply_operational_retention",
            new=AsyncMock(return_value=operational),
        ) as apply_operational,
    ):
        result = await platform_lifecycle_tasks._apply_and_commit()

    assert result == {
        "deleted_passports": 2,
        "expired_runtimes": 3,
        "deleted_discard_tombstones": 4,
    }
    apply_lifecycle.assert_awaited_once_with(session)
    apply_operational.assert_awaited_once_with(session)
    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()


async def test_lifecycle_task_rolls_back_both_policy_pages_on_failure() -> None:
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with (
        patch.object(
            platform_lifecycle_tasks,
            "AsyncSessionFactory",
            return_value=_SessionContext(session),
        ),
        patch.object(
            platform_lifecycle_tasks,
            "apply_platform_lifecycle_policies",
            new=AsyncMock(return_value=SimpleNamespace(as_dict=lambda: {})),
        ),
        patch.object(
            platform_lifecycle_tasks,
            "apply_operational_retention",
            new=AsyncMock(side_effect=RuntimeError("retention failure")),
        ),
    ):
        with pytest.raises(RuntimeError, match="retention failure"):
            await platform_lifecycle_tasks._apply_and_commit()

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()


def test_platform_scheduler_heartbeat_is_expiring_and_broker_backed() -> None:
    client = Mock()
    settings = SimpleNamespace(
        processing_worker_ping_timeout_seconds=3.0,
        redis=SimpleNamespace(broker_url="redis://broker.internal/0"),
    )
    with (
        patch.object(platform_lifecycle_tasks, "get_settings", return_value=settings),
        patch.object(
            platform_lifecycle_tasks.Redis,
            "from_url",
            return_value=client,
        ) as from_url,
    ):
        platform_lifecycle_tasks.record_platform_scheduler_heartbeat.run()

    from_url.assert_called_once_with(
        "redis://broker.internal/0",
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
        decode_responses=True,
    )
    assert client.setex.call_count == 1
    key, ttl, timestamp = client.setex.call_args.args
    assert key == platform_lifecycle_tasks.PLATFORM_SCHEDULER_HEARTBEAT_KEY
    assert ttl == 90
    assert isinstance(timestamp, str) and timestamp.endswith("+00:00")
    client.close.assert_called_once_with()


def test_celery_beat_emits_platform_heartbeat_faster_than_its_ttl() -> None:
    heartbeat = celery_app.conf.beat_schedule[
        "record-platform-scheduler-heartbeat"
    ]
    assert heartbeat["task"] == "platform.scheduler_heartbeat"
    assert heartbeat["schedule"] == 15.0
    assert heartbeat["options"] == {"queue": "passport_ocr"}
