"""Persisted deadline schedule identity and legacy marker coverage rules."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import datetime

from app.infrastructure.database.email_ai_models import EmailDetectedDeadlineModel
from app.infrastructure.email.deadline_notification_policy import (
    _aware_utc,
    _DeadlineNotificationStage,
    _ExistingStageRow,
)

_StageCoverageKey = tuple[uuid.UUID, uuid.UUID | None, uuid.UUID, str]
_StageCoverageIndex = dict[_StageCoverageKey, list[_ExistingStageRow]]


def _index_stage_coverage(rows: Sequence[_ExistingStageRow]) -> _StageCoverageIndex:
    """Retain persisted marker order within each exact authorization/stage scope."""

    by_scope: _StageCoverageIndex = {}
    for row in rows:
        key = (row[0], row[1], row[2], row[3])
        by_scope.setdefault(key, []).append(row)
    return by_scope


def _deadline_schedule_identity(due_at: datetime) -> tuple[int, str]:
    due_time = _aware_utc(due_at).replace(microsecond=0)
    schedule_epoch = int(due_time.timestamp())
    schedule_fingerprint = hashlib.sha256(due_time.isoformat().encode("ascii")).hexdigest()[:16]
    return schedule_epoch, schedule_fingerprint


def _required_due_at(deadline: EmailDetectedDeadlineModel) -> datetime:
    """Narrow the nullable persistence field after an eligibility check."""

    if deadline.due_at is None:
        raise ValueError("Eligible email deadline is missing its due time")
    return deadline.due_at


def _stage_schedule_is_covered(
    existing_rows: Sequence[_ExistingStageRow],
    *,
    deadline: EmailDetectedDeadlineModel,
    stage: _DeadlineNotificationStage,
    schedule_epoch: int,
) -> bool:
    for (
        agency_id,
        changed_entity_id,
        owner_user_id,
        event_type,
        details,
        occurred_at,
    ) in existing_rows:
        if (
            agency_id != deadline.agency_id
            or changed_entity_id != deadline.id
            or owner_user_id != deadline.owner_user_id
            or event_type != stage.event_type
        ):
            continue
        recorded_epoch = details.get("schedule_epoch")
        if (
            isinstance(recorded_epoch, int)
            and not isinstance(recorded_epoch, bool)
            and recorded_epoch == schedule_epoch
        ):
            return True
        if recorded_epoch is None and _aware_utc(occurred_at) >= _aware_utc(deadline.updated_at):
            # Legacy markers did not persist a schedule identity. Treat them as
            # current only until the deadline row is changed or corrected.
            return True
    return False


# Direct public aliases keep their existing callable metadata.
for _function in (
    _deadline_schedule_identity,
    _required_due_at,
    _stage_schedule_is_covered,
):
    _function.__module__ = "app.infrastructure.email.deadline_notifications"
del _function
