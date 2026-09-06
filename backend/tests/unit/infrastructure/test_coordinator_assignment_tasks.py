from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure import coordinator_assignment_tasks as tasks
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.repositories.coordinator_assignment_lifecycle import (
    CoordinatorAssignmentExpiryResult,
)


def test_expiry_has_its_own_minute_schedule_and_bounded_resource_limits() -> None:
    name = tasks.COORDINATOR_ASSIGNMENT_EXPIRY_TASK
    assert "app.infrastructure.coordinator_assignment_tasks" in celery_app.conf.include
    assert celery_app.conf.task_routes[name] == {"queue": "passport_ocr"}
    schedule = celery_app.conf.beat_schedule["expire-ended-trip-coordinator-assignments"]
    assert schedule == {
        "task": name,
        "schedule": 60.0,
        "options": {"queue": "passport_ocr", "expires": 60},
    }
    assert celery_app.conf.task_annotations[name] == {"soft_time_limit": 45, "time_limit": 60}


@pytest.mark.parametrize("fails", [False, True])
async def test_worker_commits_the_batch_or_rolls_back_all_changes(
    monkeypatch: pytest.MonkeyPatch,
    fails: bool,
) -> None:
    session = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(tasks, "AsyncSessionFactory", MagicMock(return_value=context))
    expiry = AsyncMock(return_value=CoordinatorAssignmentExpiryResult(1, 2, 3))
    monkeypatch.setattr(tasks, "expire_coordinator_assignments", expiry)
    if fails:
        expiry.side_effect = RuntimeError("synthetic database failure")
        with pytest.raises(RuntimeError, match="synthetic"):
            await tasks._expire_and_commit()
        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()
    else:
        assert await tasks._expire_and_commit() == {
            "groups": 1,
            "group_assignments": 2,
            "passenger_assignments": 3,
        }
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()
    expiry.assert_awaited_once_with(session)
