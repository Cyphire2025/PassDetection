"""Owner-scoped notification batches and transactional activity markers."""

from __future__ import annotations

import hashlib
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
    _STAGE_BY_NAME,
    _STAGE_EVENT_TYPES,
    _WINDOW_STAGE,
    _aware_utc,
    _deadline_notification_stage,
    _DeadlineNotificationStage,
    _DeadlineRow,
    _notification_stage_message,
)
from app.infrastructure.email.deadline_notification_visibility import _visible_linked_group_name
from app.infrastructure.repositories.notification_repository import NotificationRepository


async def create_deadline_window_notifications(
    session: AsyncSession,
    *,
    rows: Sequence[_DeadlineRow],
    now: datetime,
    window_days: int,
) -> int:
    """Create one stable notification per analysis and current deadline stage."""

    if not rows:
        return 0
    current_time = _aware_utc(now)
    cutoff = current_time + timedelta(days=window_days)
    staged_rows: list[tuple[_DeadlineRow, _DeadlineNotificationStage]] = []
    for row in rows:
        deadline = row[0]
        if deadline.status not in _ACTIVE_DEADLINE_STATUSES or deadline.due_at is None:
            continue
        stage = _deadline_notification_stage(
            due_at=deadline.due_at,
            now=current_time,
            cutoff=cutoff,
        )
        if stage is not None:
            staged_rows.append((row, stage))
    if not staged_rows:
        return 0
    staged_deadline_ids = [row[0][0].id for row in staged_rows]
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
            EmailActivityEventModel.agency_id.in_([row[0][0].agency_id for row in staged_rows]),
            EmailActivityEventModel.changed_entity_id.in_(staged_deadline_ids),
            EmailActivityEventModel.event_type.in_(_STAGE_EVENT_TYPES),
        )
    )
    existing_by_scope = _index_stage_coverage(existing_result.tuples().all())

    pending_by_analysis_stage: dict[tuple[uuid.UUID, str], list[_DeadlineRow]] = {}
    pending_markers: set[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str, int]] = set()
    for row, stage in staged_rows:
        deadline, analysis, _, _ = row
        schedule_epoch, _schedule_fingerprint = _deadline_schedule_identity(
            _required_due_at(deadline)
        )
        marker = (
            deadline.agency_id,
            deadline.id,
            deadline.owner_user_id,
            stage.event_type,
            schedule_epoch,
        )
        if marker in pending_markers:
            continue
        if _stage_schedule_is_covered(
            existing_by_scope.get(
                (deadline.agency_id, deadline.id, deadline.owner_user_id, stage.event_type),
                (),
            ),
            deadline=deadline,
            stage=stage,
            schedule_epoch=schedule_epoch,
        ):
            continue
        pending_markers.add(marker)
        pending_by_analysis_stage.setdefault(
            (analysis.id, stage.name),
            [],
        ).append(row)

    created = 0
    repository = NotificationRepository(session)
    group_names: dict[uuid.UUID, str | None] = {}
    for (
        _analysis_id,
        stage_name,
    ), rows_for_analysis in pending_by_analysis_stage.items():
        stage = _STAGE_BY_NAME[stage_name]
        deadline, analysis, message, connection = rows_for_analysis[0]
        due_times = [_aware_utc(_required_due_at(item[0])) for item in rows_for_analysis]
        needs_date_review = any(item[0].status == "review_required" for item in rows_for_analysis)
        if needs_date_review and stage is _WINDOW_STAGE:
            title = "Travel deadline needs date review"
        else:
            title = stage.title
        notification_deadline_ids = sorted(str(item[0].id) for item in rows_for_analysis)
        schedule_identities = {
            str(item[0].id): _deadline_schedule_identity(_required_due_at(item[0]))
            for item in rows_for_analysis
        }
        batch_items = sorted(
            f"{deadline_id}:{schedule_identities[deadline_id][1]}"
            for deadline_id in notification_deadline_ids
        )
        batch_key = hashlib.sha256("|".join(batch_items).encode("ascii")).hexdigest()[:16]
        if analysis.id not in group_names:
            group_names[analysis.id] = await _visible_linked_group_name(
                session,
                analysis,
            )
        group_name = group_names[analysis.id]
        await repository.create(
            agency_id=deadline.agency_id,
            user_id=deadline.owner_user_id,
            type="email_ai_deadline",
            title=title,
            message=(
                f"{len(rows_for_analysis)} detected travel "
                f"{_notification_stage_message(stage, len(rows_for_analysis))} "
                "Open the owner-scoped Operations Inbox to review it."
            ),
            entity_type="email_message",
            entity_id=str(message.id),
            priority="high" if needs_date_review else stage.priority,
            category="email_operations",
            dedupe_key=(f"email-ai:{analysis.id}:deadline-{stage.name}:{batch_key}"),
            metadata={
                "provider": connection.provider,
                "account_email": connection.email_address,
                "analysis_id": str(analysis.id),
                "deadline_ids": notification_deadline_ids,
                "deadline_count": len(rows_for_analysis),
                "next_due_at": min(due_times).isoformat(),
                "window_days": window_days,
                "notification_stage": stage.name,
                "deadline_schedule_fingerprints": {
                    deadline_id: schedule_identities[deadline_id][1]
                    for deadline_id in notification_deadline_ids
                },
                **({"group_name": group_name} if group_name is not None else {}),
            },
        )
        for item, _, _, _ in rows_for_analysis:
            due_at = _aware_utc(_required_due_at(item))
            schedule_epoch, schedule_fingerprint = schedule_identities[str(item.id)]
            session.add(
                EmailActivityEventModel(
                    agency_id=item.agency_id,
                    owner_user_id=item.owner_user_id,
                    connection_id=item.connection_id,
                    message_id=item.message_id,
                    event_key=(
                        f"email-ai-deadline:{item.id}:schedule:"
                        f"{schedule_fingerprint}:{stage.event_key_suffix}"
                    ),
                    event_type=stage.event_type,
                    stage=("warning" if needs_date_review else stage.activity_stage),
                    actor_type="system",
                    summary_code=stage.summary_code,
                    details={
                        "analysis_id": str(analysis.id),
                        "deadline_id": str(item.id),
                        "due_at": due_at.isoformat(),
                        "deadline_status": item.status,
                        "window_days": window_days,
                        "notification_stage": stage.name,
                        "schedule_epoch": schedule_epoch,
                        "schedule_fingerprint": schedule_fingerprint,
                        "notification_batch_key": batch_key,
                    },
                    ai_used=True,
                    ai_provider=analysis.ai_provider,
                    ai_model=analysis.ai_model,
                    confidence=item.confidence,
                    changed_entity_type="email_detected_deadline",
                    changed_entity_id=item.id,
                )
            )
        created += 1
    await session.flush()
    return created


# Direct public aliases keep their existing callable metadata.
create_deadline_window_notifications.__module__ = "app.infrastructure.email.deadline_notifications"
