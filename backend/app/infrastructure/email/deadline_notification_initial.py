"""Initial analysis attention coverage without duplicate deadline notifications."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.email_models import EmailActivityEventModel
from app.infrastructure.email.deadline_notification_coverage import (
    _deadline_schedule_identity,
    _index_stage_coverage,
    _required_due_at,
    _stage_schedule_is_covered,
)
from app.infrastructure.email.deadline_notification_policy import (
    _ACTIVE_DEADLINE_STATUSES,
    _IMMINENT_LEAD_TIME,
    _STAGE_EVENT_TYPES,
    _WINDOW_STAGE,
    _aware_utc,
    _deadline_notification_stage,
    _DeadlineRow,
)


async def mark_initial_deadline_window_coverage(
    session: AsyncSession,
    *,
    rows: Sequence[_DeadlineRow],
    now: datetime,
    window_days: int,
) -> int:
    """Mark deadlines covered by the analysis-level notification without duplicating it."""

    if not rows:
        return 0
    current_time = _aware_utc(now)
    cutoff = current_time + timedelta(days=window_days)
    eligible = [
        row
        for row in rows
        if row[0].status in _ACTIVE_DEADLINE_STATUSES
        and row[0].due_at is not None
        and _aware_utc(row[0].due_at) <= cutoff
    ]
    if not eligible:
        return 0
    existing_result = await session.execute(
        select(
            EmailActivityEventModel.agency_id,
            EmailActivityEventModel.changed_entity_id,
            EmailActivityEventModel.owner_user_id,
            EmailActivityEventModel.event_type,
            EmailActivityEventModel.details,
            EmailActivityEventModel.occurred_at,
        ).where(
            EmailActivityEventModel.changed_entity_type == "email_detected_deadline",
            EmailActivityEventModel.agency_id.in_([row[0].agency_id for row in eligible]),
            EmailActivityEventModel.changed_entity_id.in_([row[0].id for row in eligible]),
            EmailActivityEventModel.event_type.in_(_STAGE_EVENT_TYPES),
        )
    )
    existing_by_scope = _index_stage_coverage(existing_result.tuples().all())
    pending_markers: set[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str, int]] = set()
    created = 0
    for deadline, analysis, _, _ in eligible:
        due_at = _aware_utc(_required_due_at(deadline))
        schedule_epoch, schedule_fingerprint = _deadline_schedule_identity(due_at)
        current_stage = _deadline_notification_stage(
            due_at=due_at,
            now=current_time,
            cutoff=cutoff,
        )
        covered_stages = [_WINDOW_STAGE]
        if current_stage is not None and current_stage is not _WINDOW_STAGE:
            covered_stages.append(current_stage)
        for stage in covered_stages:
            marker = (
                deadline.agency_id,
                deadline.id,
                deadline.owner_user_id,
                stage.event_type,
                schedule_epoch,
            )
            if marker in pending_markers or _stage_schedule_is_covered(
                existing_by_scope.get(
                    (deadline.agency_id, deadline.id, deadline.owner_user_id, stage.event_type),
                    (),
                ),
                deadline=deadline,
                stage=stage,
                schedule_epoch=schedule_epoch,
            ):
                continue
            activity_stage = stage.activity_stage
            if stage is _WINDOW_STAGE and (
                due_at <= current_time + _IMMINENT_LEAD_TIME or deadline.status == "review_required"
            ):
                activity_stage = "warning"
            session.add(
                EmailActivityEventModel(
                    agency_id=deadline.agency_id,
                    owner_user_id=deadline.owner_user_id,
                    connection_id=deadline.connection_id,
                    message_id=deadline.message_id,
                    event_key=(
                        f"email-ai-deadline:{deadline.id}:schedule:"
                        f"{schedule_fingerprint}:{stage.event_key_suffix}"
                    ),
                    event_type=stage.event_type,
                    stage=activity_stage,
                    actor_type="system",
                    summary_code=stage.summary_code,
                    details={
                        "analysis_id": str(analysis.id),
                        "deadline_id": str(deadline.id),
                        "due_at": due_at.isoformat(),
                        "deadline_status": deadline.status,
                        "window_days": window_days,
                        "notification_mode": "analysis_attention",
                        "notification_stage": stage.name,
                        "schedule_epoch": schedule_epoch,
                        "schedule_fingerprint": schedule_fingerprint,
                    },
                    ai_used=True,
                    ai_provider=analysis.ai_provider,
                    ai_model=analysis.ai_model,
                    confidence=deadline.confidence,
                    changed_entity_type="email_detected_deadline",
                    changed_entity_id=deadline.id,
                )
            )
            pending_markers.add(marker)
            created += 1
    await session.flush()
    return created


# Direct public aliases keep their existing callable metadata.
mark_initial_deadline_window_coverage.__module__ = "app.infrastructure.email.deadline_notifications"
