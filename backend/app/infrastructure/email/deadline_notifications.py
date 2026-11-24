"""Public deadline scanner and stable legacy notification API aliases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import BigInteger, and_, case, cast, exists, extract, or_, select

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
from app.infrastructure.database.models import UserModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.email.deadline_notification_coverage import (
    _deadline_schedule_identity as _deadline_schedule_identity,
)
from app.infrastructure.email.deadline_notification_coverage import (
    _required_due_at as _required_due_at,
)
from app.infrastructure.email.deadline_notification_coverage import (
    _stage_schedule_is_covered as _stage_schedule_is_covered,
)
from app.infrastructure.email.deadline_notification_emit import create_deadline_window_notifications
from app.infrastructure.email.deadline_notification_initial import (
    mark_initial_deadline_window_coverage as mark_initial_deadline_window_coverage,
)
from app.infrastructure.email.deadline_notification_policy import (
    _ACTIVE_ANALYSIS_STATUSES,
    _ACTIVE_DEADLINE_STATUSES,
    _DUE_STAGE,
    _DUE_STAGE_DURATION,
    _IMMINENT_LEAD_TIME,
    _IMMINENT_STAGE,
    _OFFICE_ROLES,
    _OVERDUE_STAGE,
    _SCAN_BATCH_SIZE,
    _WINDOW_STAGE,
    _aware_utc,
)
from app.infrastructure.email.deadline_notification_policy import (
    _DEADLINE_NOTIFICATION_STAGES as _DEADLINE_NOTIFICATION_STAGES,
)
from app.infrastructure.email.deadline_notification_policy import _STAGE_BY_NAME as _STAGE_BY_NAME
from app.infrastructure.email.deadline_notification_policy import (
    _STAGE_EVENT_TYPES as _STAGE_EVENT_TYPES,
)
from app.infrastructure.email.deadline_notification_policy import (
    _deadline_notification_stage as _deadline_notification_stage,
)
from app.infrastructure.email.deadline_notification_policy import (
    _DeadlineNotificationStage as _DeadlineNotificationStage,
)
from app.infrastructure.email.deadline_notification_policy import _DeadlineRow as _DeadlineRow
from app.infrastructure.email.deadline_notification_policy import (
    _ExistingStageRow as _ExistingStageRow,
)
from app.infrastructure.email.deadline_notification_policy import (
    _notification_stage_message as _notification_stage_message,
)
from app.infrastructure.email.deadline_notification_visibility import (
    _visible_linked_group_name as _visible_linked_group_name,
)


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
