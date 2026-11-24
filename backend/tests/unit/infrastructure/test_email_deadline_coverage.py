from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.infrastructure.database.email_ai_models import EmailDetectedDeadlineModel
from app.infrastructure.email import deadline_notifications as api
from app.infrastructure.email.deadline_notification_coverage import _index_stage_coverage

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _deadline() -> EmailDetectedDeadlineModel:
    return EmailDetectedDeadlineModel(
        id=uuid.UUID(int=1),
        agency_id=uuid.UUID(int=2),
        owner_user_id=uuid.UUID(int=3),
        due_at=NOW + timedelta(days=5),
        updated_at=NOW,
    )


def test_index_retains_exact_scope_row_identity_and_order() -> None:
    deadline = _deadline()
    key = (deadline.agency_id, deadline.id, deadline.owner_user_id, api._WINDOW_STAGE.event_type)
    first = (*key, {"schedule_epoch": 1}, NOW)
    second = (*key, {}, NOW + timedelta(seconds=1))
    other_scopes = [
        (uuid.UUID(int=4), *key[1:]),
        (key[0], None, *key[2:]),
        (*key[:2], uuid.UUID(int=4), key[3]),
        (*key[:3], api._DUE_STAGE.event_type),
    ]
    unrelated = [(*scope, {"schedule_epoch": 1}, NOW) for scope in other_scopes]
    rows = [first, *unrelated, second]

    indexed = _index_stage_coverage(rows)

    assert list(indexed) == [key, *other_scopes]
    assert indexed[key] == [first, second]
    assert indexed[key][0] is first and indexed[key][1] is second
    for row, scope in zip(unrelated, other_scopes, strict=True):
        assert indexed[scope][0] is row


@pytest.mark.parametrize(
    ("epoch_kind", "occurred_offset", "covered"),
    [
        ("current", -1, True),
        ("old", 1, False),
        ("boolean", 1, False),
        ("float", 1, False),
        ("missing", -1, False),
        ("missing", 0, True),
        ("missing", 1, True),
    ],
)
def test_index_preserves_corrected_schedule_and_legacy_marker_rules(
    epoch_kind: str, occurred_offset: int, covered: bool
) -> None:
    deadline = _deadline()
    epoch, _ = api._deadline_schedule_identity(deadline.due_at)
    values = {"current": epoch, "old": epoch - 1, "boolean": True, "float": float(epoch)}
    details = {} if epoch_kind == "missing" else {"schedule_epoch": values[epoch_kind]}
    key = (deadline.agency_id, deadline.id, deadline.owner_user_id, api._WINDOW_STAGE.event_type)
    # The timestamp remains a naive persisted UTC value, as returned by SQLite.
    occurred = (NOW + timedelta(seconds=occurred_offset)).replace(tzinfo=None)
    row = (*key, details, occurred)
    indexed = _index_stage_coverage([row])

    for rows in ([row], indexed[key]):
        assert (
            api._stage_schedule_is_covered(
                rows, deadline=deadline, stage=api._WINDOW_STAGE, schedule_epoch=epoch
            )
            is covered
        )


@pytest.mark.parametrize("scope_index", range(4))
def test_foreign_scope_never_suppresses_the_deadline(scope_index: int) -> None:
    deadline = _deadline()
    epoch, _ = api._deadline_schedule_identity(deadline.due_at)
    key = (deadline.agency_id, deadline.id, deadline.owner_user_id, api._WINDOW_STAGE.event_type)
    different = list(key)
    different[scope_index] = "other-stage" if scope_index == 3 else uuid.UUID(int=99)
    rows = [(*different, {"schedule_epoch": epoch}, NOW)]
    indexed = _index_stage_coverage(rows)

    for values in (rows, indexed.get(key, ())):
        assert not api._stage_schedule_is_covered(
            values, deadline=deadline, stage=api._WINDOW_STAGE, schedule_epoch=epoch
        )


def test_missing_due_time_is_rejected_after_eligibility_narrowing() -> None:
    deadline = _deadline()
    deadline.due_at = None
    with pytest.raises(ValueError, match="missing its due time"):
        api._required_due_at(deadline)
