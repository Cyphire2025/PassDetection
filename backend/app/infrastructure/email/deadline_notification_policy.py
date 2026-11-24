"""Typed deadline stages, eligibility constants and shared calendar policy."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.domain.entities.entities import UserRole
from app.infrastructure.database.email_ai_models import (
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
)
from app.infrastructure.database.email_models import EmailConnectionModel, EmailMessageModel

_ACTIVE_DEADLINE_STATUSES = {"detected", "review_required", "acknowledged"}

_ACTIVE_ANALYSIS_STATUSES = {"completed", "review_required"}

_OFFICE_ROLES = {
    UserRole.SUPER_ADMIN.value,
    UserRole.AGENCY_ADMIN.value,
    UserRole.AGENCY_MANAGER.value,
    UserRole.AGENCY_STAFF.value,
}

_SCAN_BATCH_SIZE = 200

_IMMINENT_LEAD_TIME = timedelta(hours=24)

_DUE_STAGE_DURATION = timedelta(hours=24)


@dataclass(frozen=True)
class _DeadlineNotificationStage:
    name: str
    event_type: str
    event_key_suffix: str
    title: str
    summary_code: str
    activity_stage: str
    priority: str


# Keep the original public dataclass/pickle identity.
_DeadlineNotificationStage.__module__ = "app.infrastructure.email.deadline_notifications"

_WINDOW_STAGE = _DeadlineNotificationStage(
    name="window",
    event_type="ai_deadline_window_notified",
    event_key_suffix="window-notified",
    title="Travel deadline entered the action window",
    summary_code="email_ai_deadline_window_notified",
    activity_stage="info",
    priority="normal",
)

_IMMINENT_STAGE = _DeadlineNotificationStage(
    name="24h",
    event_type="ai_deadline_24h_notified",
    event_key_suffix="24h-notified",
    title="Travel deadline is due within 24 hours",
    summary_code="email_ai_deadline_24h_notified",
    activity_stage="warning",
    priority="high",
)

_DUE_STAGE = _DeadlineNotificationStage(
    name="due",
    event_type="ai_deadline_due_notified",
    event_key_suffix="due-notified",
    title="Travel deadline is due now",
    summary_code="email_ai_deadline_due_notified",
    activity_stage="warning",
    priority="high",
)

_OVERDUE_STAGE = _DeadlineNotificationStage(
    name="overdue",
    event_type="ai_deadline_overdue_notified",
    event_key_suffix="overdue-notified",
    title="Travel deadline is overdue",
    summary_code="email_ai_deadline_overdue_notified",
    activity_stage="warning",
    priority="high",
)

_DEADLINE_NOTIFICATION_STAGES = (
    _WINDOW_STAGE,
    _IMMINENT_STAGE,
    _DUE_STAGE,
    _OVERDUE_STAGE,
)

_STAGE_BY_NAME = {stage.name: stage for stage in _DEADLINE_NOTIFICATION_STAGES}

_STAGE_EVENT_TYPES = {stage.event_type for stage in _DEADLINE_NOTIFICATION_STAGES}

_DeadlineRow = tuple[
    EmailDetectedDeadlineModel,
    EmailAiAnalysisModel,
    EmailMessageModel,
    EmailConnectionModel,
]

_ExistingStageRow = tuple[
    uuid.UUID,
    uuid.UUID | None,
    uuid.UUID,
    str,
    dict[str, object],
    datetime,
]


def _deadline_notification_stage(
    *,
    due_at: datetime,
    now: datetime,
    cutoff: datetime,
) -> _DeadlineNotificationStage | None:
    due_time = _aware_utc(due_at)
    if due_time > cutoff:
        return None
    if due_time <= now - _DUE_STAGE_DURATION:
        return _OVERDUE_STAGE
    if due_time <= now:
        return _DUE_STAGE
    if due_time <= now + _IMMINENT_LEAD_TIME:
        return _IMMINENT_STAGE
    return _WINDOW_STAGE


def _notification_stage_message(
    stage: _DeadlineNotificationStage,
    count: int,
) -> str:
    noun = "deadline" if count == 1 else "deadlines"
    if stage is _WINDOW_STAGE:
        verb = "needs" if count == 1 else "need"
        return f"{noun} now {verb} attention."
    verb = "is" if count == 1 else "are"
    if stage is _IMMINENT_STAGE:
        return f"{noun} {verb} due within 24 hours."
    if stage is _DUE_STAGE:
        return f"{noun} {verb} due now."
    return f"{noun} {verb} overdue."


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# Direct public aliases keep their existing callable metadata.
for _function in (
    _deadline_notification_stage,
    _notification_stage_message,
    _aware_utc,
):
    _function.__module__ = "app.infrastructure.email.deadline_notifications"
del _function
