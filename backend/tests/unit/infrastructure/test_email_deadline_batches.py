from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.database.email_ai_models import (
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
)
from app.infrastructure.database.email_models import EmailConnectionModel, EmailMessageModel
from app.infrastructure.email import deadline_notification_emit as emit
from app.infrastructure.email import deadline_notification_initial as initial
from app.infrastructure.email import deadline_notifications as api

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _rows(count: int):
    agency, owner, connection_id = [uuid.UUID(int=index) for index in (1, 2, 3)]
    connection = EmailConnectionModel(
        id=connection_id,
        agency_id=agency,
        owner_user_id=owner,
        provider="gmail",
        email_address="owner@example.test",
    )
    rows = []
    for index in range(count):
        # Each actual AI analysis is bounded to eight deadlines.
        analysis_id = uuid.UUID(int=100 + index // 8)
        message_id = uuid.UUID(int=200 + index // 8)
        analysis = EmailAiAnalysisModel(
            id=analysis_id,
            agency_id=agency,
            owner_user_id=owner,
            connection_id=connection_id,
            message_id=message_id,
            ai_provider="google",
            ai_model="synthetic-not-used",
            result_json={},
        )
        message = EmailMessageModel(id=message_id)
        deadline = EmailDetectedDeadlineModel(
            id=uuid.UUID(int=1000 + index),
            agency_id=agency,
            owner_user_id=owner,
            connection_id=connection_id,
            message_id=message_id,
            analysis_id=analysis_id,
            due_at=NOW + timedelta(hours=12, seconds=index),
            updated_at=NOW,
            status="detected",
            confidence=0.95,
        )
        rows.append((deadline, analysis, message, connection))
    return rows


class _Session:
    def __init__(self, rows=()):
        self.events = []
        self.flush = AsyncMock()
        self.execute = AsyncMock(
            return_value=SimpleNamespace(tuples=lambda: SimpleNamespace(all=lambda: rows))
        )

    def add(self, event):
        self.events.append(event)


class _CountedRows(Sequence):
    def __init__(self, rows, counts, name):
        self.rows, self.counts, self.name = rows, counts, name

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return self.rows[index]

    def __iter__(self):
        for row in self.rows:
            self.counts[self.name] += 1
            yield row


@pytest.mark.parametrize(("mode", "count", "created"), [("emit", 200, 25), ("initial", 8, 16)])
async def test_corrected_schedule_batches_use_only_the_matching_marker_bucket(
    monkeypatch, mode: str, count: int, created: int
) -> None:
    owner = emit if mode == "emit" else initial
    function = (
        api.create_deadline_window_notifications
        if mode == "emit"
        else api.mark_initial_deadline_window_coverage
    )
    rows = _rows(count)
    existing = []
    for deadline, *_rest in rows:
        old_epoch, _ = api._deadline_schedule_identity(deadline.due_at - timedelta(days=2))
        for stage in api._DEADLINE_NOTIFICATION_STAGES:
            existing.append(
                (
                    deadline.agency_id,
                    deadline.id,
                    deadline.owner_user_id,
                    stage.event_type,
                    {"schedule_epoch": old_epoch},
                    NOW,
                )
            )
    counts = {"index": 0, "rule": 0}
    original_index, original_rule = owner._index_stage_coverage, owner._stage_schedule_is_covered

    def index(values):
        return original_index(_CountedRows(values, counts, "index"))

    def rule(values, **kwargs):
        return original_rule(_CountedRows(values, counts, "rule"), **kwargs)

    monkeypatch.setattr(owner, "_index_stage_coverage", index)
    monkeypatch.setattr(owner, "_stage_schedule_is_covered", rule)
    notifications = AsyncMock()
    monkeypatch.setattr(emit.NotificationRepository, "create", notifications)
    monkeypatch.setattr(emit, "_visible_linked_group_name", AsyncMock(return_value=None))
    session = _Session(existing)

    assert await function(session, rows=rows, now=NOW, window_days=14) == created

    expected_events = count if mode == "emit" else count * 2
    assert counts == {"index": count * 4, "rule": expected_events}
    assert len(session.events) == expected_events
    assert len({event.event_key for event in session.events}) == expected_events
    assert notifications.await_count == (created if mode == "emit" else 0)
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()


@pytest.mark.parametrize("mode", ["emit", "initial"])
@pytest.mark.parametrize("eligibility", ["empty", "closed", "missing", "outside"])
async def test_ineligible_batches_never_query_or_flush(mode: str, eligibility: str) -> None:
    function = (
        api.create_deadline_window_notifications
        if mode == "emit"
        else api.mark_initial_deadline_window_coverage
    )
    rows = _rows(1)
    if eligibility == "empty":
        rows = []
    elif eligibility == "closed":
        rows[0][0].status = "dismissed"
    elif eligibility == "missing":
        rows[0][0].due_at = None
    else:
        rows[0][0].due_at = NOW + timedelta(days=15)
    session = _Session()

    assert await function(session, rows=rows, now=NOW, window_days=14) == 0

    session.execute.assert_not_awaited()
    session.flush.assert_not_awaited()
    assert session.events == []


@pytest.mark.parametrize("mode", ["emit", "initial"])
@pytest.mark.parametrize("already_covered", [False, True])
async def test_duplicate_review_rows_keep_one_event_and_current_coverage_suppresses_it(
    monkeypatch, mode: str, already_covered: bool
) -> None:
    function = (
        api.create_deadline_window_notifications
        if mode == "emit"
        else api.mark_initial_deadline_window_coverage
    )
    rows = _rows(1)
    deadline = rows[0][0]
    deadline.due_at = NOW + timedelta(days=5)
    deadline.status = "review_required"
    epoch, _ = api._deadline_schedule_identity(deadline.due_at)
    existing = [
        (
            deadline.agency_id,
            deadline.id,
            deadline.owner_user_id,
            api._WINDOW_STAGE.event_type,
            {"schedule_epoch": epoch},
            NOW,
        )
    ]
    session = _Session(existing if already_covered else ())
    notifications = AsyncMock()
    monkeypatch.setattr(emit.NotificationRepository, "create", notifications)
    monkeypatch.setattr(emit, "_visible_linked_group_name", AsyncMock(return_value=None))

    expected = 0 if already_covered else 1
    assert await function(session, rows=rows * 2, now=NOW, window_days=14) == expected

    assert len(session.events) == expected
    if expected:
        assert session.events[0].stage == "warning"
        if mode == "emit":
            assert notifications.call_args.kwargs["title"] == "Travel deadline needs date review"
            assert notifications.call_args.kwargs["priority"] == "high"
    assert notifications.await_count == (expected if mode == "emit" else 0)
    session.flush.assert_awaited_once()
