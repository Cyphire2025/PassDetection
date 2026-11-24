"""Fair per-owner seed SQL, preserving exact current eligibility and ranking."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Select, and_, case, exists, func, or_, select

from app.application.use_cases.email_integrations.rollout_policy import (
    email_ai_disabled_policy_exists,
)
from app.domain.entities.entities import UserRole
from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.database.email_models import EmailConnectionModel, EmailMessageModel
from app.infrastructure.database.models import UserModel


def build_seed_query(
    *,
    now: datetime,
    starvation_age: timedelta,
    per_owner_limit: int,
    batch_size: int,
    office_roles: set[str],
    settled_statuses: set[str],
) -> Select[tuple[EmailMessageModel, EmailConnectionModel]]:
    ranked_seed_candidates = (
        select(
            EmailMessageModel.id.label("message_id"),
            EmailMessageModel.received_at.label("message_received_at"),
            func.row_number()
            .over(
                partition_by=EmailMessageModel.owner_user_id,
                order_by=(
                    EmailMessageModel.received_at.desc(),
                    EmailMessageModel.id.desc(),
                ),
            )
            .label("newest_rank"),
            func.row_number()
            .over(
                partition_by=EmailMessageModel.owner_user_id,
                order_by=(
                    EmailMessageModel.received_at.asc(),
                    EmailMessageModel.id.asc(),
                ),
            )
            .label("oldest_rank"),
            func.max(
                case(
                    (
                        EmailMessageModel.received_at <= now - starvation_age,
                        1,
                    ),
                    else_=0,
                )
            )
            .over(partition_by=EmailMessageModel.owner_user_id)
            .label("has_starved"),
        )
        .join(
            EmailConnectionModel,
            and_(
                EmailConnectionModel.id == EmailMessageModel.connection_id,
                EmailConnectionModel.agency_id == EmailMessageModel.agency_id,
                EmailConnectionModel.owner_user_id == EmailMessageModel.owner_user_id,
            ),
        )
        .join(UserModel, UserModel.id == EmailMessageModel.owner_user_id)
        .where(
            EmailMessageModel.processing_status.in_(settled_statuses),
            EmailMessageModel.relevance_status != "failed",
            EmailMessageModel.evidence_json["human_marked_unrelated"].as_boolean().is_not(True),
            EmailConnectionModel.status.in_({"active", "failing"}),
            EmailConnectionModel.ai_processing_enabled.is_(True),
            EmailConnectionModel.ai_enabled_at.is_not(None),
            EmailMessageModel.received_at >= EmailConnectionModel.ai_enabled_at,
            UserModel.is_active.is_(True),
            UserModel.role.in_(office_roles),
            or_(
                UserModel.role == UserRole.SUPER_ADMIN.value,
                UserModel.agency_id == EmailMessageModel.agency_id,
            ),
            ~email_ai_disabled_policy_exists(
                agency_id=EmailMessageModel.agency_id,
                owner_user_id=EmailMessageModel.owner_user_id,
                connection_id=EmailMessageModel.connection_id,
            ),
            ~exists(
                select(1).where(
                    EmailAiAnalysisModel.message_id == EmailMessageModel.id,
                    EmailAiAnalysisModel.owner_user_id == EmailMessageModel.owner_user_id,
                )
            ),
        )
        .subquery()
    )
    prioritized_seed_candidates = (
        select(
            ranked_seed_candidates.c.message_id,
            ranked_seed_candidates.c.message_received_at,
            case(
                (
                    and_(
                        ranked_seed_candidates.c.has_starved == 1,
                        ranked_seed_candidates.c.oldest_rank == 1,
                    ),
                    0,
                ),
                (ranked_seed_candidates.c.newest_rank == 1, 1),
                else_=2,
            ).label("slot_order"),
            case(
                (
                    and_(
                        ranked_seed_candidates.c.has_starved == 1,
                        ranked_seed_candidates.c.oldest_rank == 1,
                    ),
                    ranked_seed_candidates.c.message_received_at,
                ),
                else_=None,
            ).label("starved_received_at"),
        )
        .where(
            or_(
                ranked_seed_candidates.c.newest_rank == 1,
                and_(
                    ranked_seed_candidates.c.has_starved == 1,
                    ranked_seed_candidates.c.oldest_rank == 1,
                ),
                and_(
                    ranked_seed_candidates.c.has_starved == 0,
                    ranked_seed_candidates.c.newest_rank <= per_owner_limit,
                ),
            )
        )
        .subquery()
    )
    return (
        select(EmailMessageModel, EmailConnectionModel)
        .join(
            prioritized_seed_candidates,
            prioritized_seed_candidates.c.message_id == EmailMessageModel.id,
        )
        .join(
            EmailConnectionModel,
            and_(
                EmailConnectionModel.id == EmailMessageModel.connection_id,
                EmailConnectionModel.agency_id == EmailMessageModel.agency_id,
                EmailConnectionModel.owner_user_id == EmailMessageModel.owner_user_id,
            ),
        )
        .order_by(
            prioritized_seed_candidates.c.slot_order.asc(),
            prioritized_seed_candidates.c.starved_received_at.asc(),
            prioritized_seed_candidates.c.message_received_at.desc(),
            EmailMessageModel.id.desc(),
        )
        .limit(batch_size)
        .with_for_update(skip_locked=True, of=EmailMessageModel)
    )
