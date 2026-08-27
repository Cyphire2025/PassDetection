"""Idempotent staged deadline alerts for owner-scoped email intelligence."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import BigInteger, and_, case, cast, exists, extract, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.email_integrations.rollout_policy import (
    email_ai_disabled_policy_exists,
)
from app.core.config.settings import Settings, get_settings
from app.domain.entities.entities import UserRole
from app.infrastructure.database.email_ai_models import (
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
)
from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailConnectionModel,
    EmailMessageModel,
)
from app.infrastructure.database.models import ClientGroupModel, UserModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository

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


async def scan_email_ai_deadline_notifications(
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
) -> int:
    """Notify eligible owners when persisted deadlines reach their current stage."""

    settings = settings or get_settings()
    if not settings.email_ai_notifications_ready:
        return 0
    current_time = _aware_utc(now or datetime.now(tz=UTC))
    cutoff = current_time + timedelta(days=settings.email_ai_deadline_notification_window_days)
    current_stage_event_type = case(
        (
            EmailDetectedDeadlineModel.due_at <= current_time - _DUE_STAGE_DURATION,
            _OVERDUE_STAGE.event_type,
        ),
        (
            EmailDetectedDeadlineModel.due_at <= current_time,
            _DUE_STAGE.event_type,
        ),
        (
            EmailDetectedDeadlineModel.due_at <= current_time + _IMMINENT_LEAD_TIME,
            _IMMINENT_STAGE.event_type,
        ),
        else_=_WINDOW_STAGE.event_type,
    )
    deadline_schedule_epoch = cast(
        extract("epoch", EmailDetectedDeadlineModel.due_at),
        BigInteger,
    )
    activity_schedule_epoch = EmailActivityEventModel.details["schedule_epoch"].as_integer()
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(
                EmailDetectedDeadlineModel,
                EmailAiAnalysisModel,
                EmailMessageModel,
                EmailConnectionModel,
            )
            .join(
                EmailAiAnalysisModel,
                and_(
                    EmailAiAnalysisModel.id == EmailDetectedDeadlineModel.analysis_id,
                    EmailAiAnalysisModel.message_id == EmailDetectedDeadlineModel.message_id,
                    EmailAiAnalysisModel.connection_id == EmailDetectedDeadlineModel.connection_id,
                    EmailAiAnalysisModel.agency_id == EmailDetectedDeadlineModel.agency_id,
                    EmailAiAnalysisModel.owner_user_id == EmailDetectedDeadlineModel.owner_user_id,
                ),
            )
            .join(
                EmailMessageModel,
                and_(
                    EmailMessageModel.id == EmailDetectedDeadlineModel.message_id,
                    EmailMessageModel.connection_id == EmailDetectedDeadlineModel.connection_id,
                    EmailMessageModel.agency_id == EmailDetectedDeadlineModel.agency_id,
                    EmailMessageModel.owner_user_id == EmailDetectedDeadlineModel.owner_user_id,
                ),
            )
            .join(
                EmailConnectionModel,
                and_(
                    EmailConnectionModel.id == EmailDetectedDeadlineModel.connection_id,
                    EmailConnectionModel.agency_id == EmailDetectedDeadlineModel.agency_id,
                    EmailConnectionModel.owner_user_id == EmailDetectedDeadlineModel.owner_user_id,
                ),
            )
            .join(
                UserModel,
                UserModel.id == EmailDetectedDeadlineModel.owner_user_id,
            )
            .where(
                EmailDetectedDeadlineModel.status.in_(_ACTIVE_DEADLINE_STATUSES),
                EmailDetectedDeadlineModel.due_at.is_not(None),
                EmailDetectedDeadlineModel.due_at <= cutoff,
                EmailAiAnalysisModel.status.in_(_ACTIVE_ANALYSIS_STATUSES),
                EmailConnectionModel.status.in_({"active", "failing"}),
                EmailConnectionModel.ai_processing_enabled.is_(True),
                UserModel.is_active.is_(True),
                UserModel.role.in_(_OFFICE_ROLES),
                or_(
                    UserModel.role == UserRole.SUPER_ADMIN.value,
                    UserModel.agency_id == EmailDetectedDeadlineModel.agency_id,
                ),
                ~email_ai_disabled_policy_exists(
                    agency_id=EmailDetectedDeadlineModel.agency_id,
                    owner_user_id=EmailDetectedDeadlineModel.owner_user_id,
                    connection_id=EmailDetectedDeadlineModel.connection_id,
                ),
                ~exists(
                    select(1).where(
                        EmailActivityEventModel.changed_entity_type == "email_detected_deadline",
                        EmailActivityEventModel.changed_entity_id == EmailDetectedDeadlineModel.id,
                        EmailActivityEventModel.agency_id == EmailDetectedDeadlineModel.agency_id,
                        EmailActivityEventModel.owner_user_id
                        == EmailDetectedDeadlineModel.owner_user_id,
                        EmailActivityEventModel.event_type == current_stage_event_type,
                        or_(
                            activity_schedule_epoch == deadline_schedule_epoch,
                            and_(
                                activity_schedule_epoch.is_(None),
                                EmailActivityEventModel.occurred_at
                                >= EmailDetectedDeadlineModel.updated_at,
                            ),
                        ),
                    )
                ),
            )
            .order_by(
                EmailDetectedDeadlineModel.due_at.asc(),
                EmailDetectedDeadlineModel.id.asc(),
            )
            .limit(_SCAN_BATCH_SIZE)
            .with_for_update(
                skip_locked=True,
                of=EmailDetectedDeadlineModel,
            )
        )
        notified = await create_deadline_window_notifications(
            session,
            rows=list(result.tuples().all()),
            now=current_time,
            window_days=settings.email_ai_deadline_notification_window_days,
        )
        await session.commit()
        return notified


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
    existing_rows = list(existing_result.tuples().all())

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
            existing_rows,
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
        notification_deadline_ids = sorted(
            str(item[0].id) for item in rows_for_analysis
        )
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
                **(
                    {"group_name": group_name}
                    if group_name is not None
                    else {}
                ),
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
        if recorded_epoch is None and _aware_utc(occurred_at) >= _aware_utc(
            deadline.updated_at
        ):
            # Legacy markers did not persist a schedule identity. Treat them as
            # current only until the deadline row is changed or corrected.
            return True
    return False


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
    existing_rows = list(existing_result.tuples().all())
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
                existing_rows,
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


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _visible_linked_group_name(
    session: AsyncSession,
    analysis: EmailAiAnalysisModel,
) -> str | None:
    """Resolve a linked group only through the current owner's live visibility."""

    raw_group_id = (analysis.result_json or {}).get("linked_group_id")
    if not isinstance(raw_group_id, str):
        return None
    try:
        group_id = uuid.UUID(raw_group_id)
    except ValueError:
        return None
    owner = await UserRepository(session).get_by_id(
        analysis.owner_user_id
    )
    if (
        owner is None
        or not owner.is_active
        or (
            owner.role != UserRole.SUPER_ADMIN
            and owner.agency_id != analysis.agency_id
        )
    ):
        return None
    statement = select(ClientGroupModel).where(
        ClientGroupModel.id == group_id,
        ClientGroupModel.agency_id == analysis.agency_id,
        ClientGroupModel.status.notin_({"archived", "deleted"}),
    )
    group = await session.scalar(
        AuthorizationPolicy.apply_group_visibility_scope(
            statement,
            owner,
        )
    )
    if group is None:
        return None
    normalized = " ".join(group.name.split())[:160]
    return normalized or None
