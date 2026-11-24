"""Fair pending/expired claim SQL with the original current-source joins."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Select, and_, case, func, or_, select

from app.application.use_cases.email_integrations.rollout_policy import (
    email_ai_disabled_policy_exists,
)
from app.domain.entities.entities import UserRole
from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.database.email_models import EmailConnectionModel, EmailMessageModel
from app.infrastructure.database.models import UserModel


def build_claim_query(
    *,
    now: datetime,
    starvation_age: timedelta,
    per_owner_limit: int,
    claim_limit: int,
    max_attempts: int,
    office_roles: set[str],
    settled_statuses: set[str],
) -> Select[tuple[EmailAiAnalysisModel, EmailConnectionModel]]:
    eligible_claims = (
        select(
            EmailAiAnalysisModel.id.label("analysis_id"),
            EmailAiAnalysisModel.owner_user_id.label("owner_user_id"),
            EmailAiAnalysisModel.created_at.label("created_at"),
            EmailMessageModel.received_at.label("message_received_at"),
            func.row_number()
            .over(
                partition_by=EmailAiAnalysisModel.owner_user_id,
                order_by=(
                    EmailMessageModel.received_at.desc(),
                    EmailAiAnalysisModel.id.desc(),
                ),
            )
            .label("newest_rank"),
            func.row_number()
            .over(
                partition_by=EmailAiAnalysisModel.owner_user_id,
                order_by=(
                    EmailMessageModel.received_at.asc(),
                    EmailAiAnalysisModel.id.asc(),
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
            .over(partition_by=EmailAiAnalysisModel.owner_user_id)
            .label("has_starved"),
        )
        .join(
            EmailMessageModel,
            and_(
                EmailMessageModel.id == EmailAiAnalysisModel.message_id,
                EmailMessageModel.connection_id == EmailAiAnalysisModel.connection_id,
                EmailMessageModel.agency_id == EmailAiAnalysisModel.agency_id,
                EmailMessageModel.owner_user_id == EmailAiAnalysisModel.owner_user_id,
            ),
        )
        .join(
            EmailConnectionModel,
            and_(
                EmailConnectionModel.id == EmailAiAnalysisModel.connection_id,
                EmailConnectionModel.agency_id == EmailAiAnalysisModel.agency_id,
                EmailConnectionModel.owner_user_id == EmailAiAnalysisModel.owner_user_id,
            ),
        )
        .join(UserModel, UserModel.id == EmailAiAnalysisModel.owner_user_id)
        .where(
            or_(
                and_(
                    EmailAiAnalysisModel.status == "pending",
                    or_(
                        EmailAiAnalysisModel.next_attempt_at.is_(None),
                        EmailAiAnalysisModel.next_attempt_at <= now,
                    ),
                ),
                and_(
                    EmailAiAnalysisModel.status == "processing",
                    EmailAiAnalysisModel.lease_expires_at <= now,
                ),
            ),
            EmailAiAnalysisModel.attempt_count < max_attempts,
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
                UserModel.agency_id == EmailAiAnalysisModel.agency_id,
            ),
            ~email_ai_disabled_policy_exists(
                agency_id=EmailAiAnalysisModel.agency_id,
                owner_user_id=EmailAiAnalysisModel.owner_user_id,
                connection_id=EmailAiAnalysisModel.connection_id,
            ),
        )
        .subquery()
    )
    ranked_claim_candidates = (
        select(
            eligible_claims.c.analysis_id,
            eligible_claims.c.message_received_at,
            case(
                (
                    and_(
                        eligible_claims.c.has_starved == 1,
                        eligible_claims.c.oldest_rank == 1,
                    ),
                    0,
                ),
                (eligible_claims.c.newest_rank == 1, 1),
                else_=2,
            ).label("slot_order"),
            case(
                (
                    and_(
                        eligible_claims.c.has_starved == 1,
                        eligible_claims.c.oldest_rank == 1,
                    ),
                    eligible_claims.c.message_received_at,
                ),
                else_=None,
            ).label("starved_received_at"),
        )
        .where(
            or_(
                eligible_claims.c.newest_rank == 1,
                and_(
                    eligible_claims.c.has_starved == 1,
                    eligible_claims.c.oldest_rank == 1,
                ),
                and_(
                    eligible_claims.c.has_starved == 0,
                    eligible_claims.c.newest_rank <= per_owner_limit,
                ),
            )
        )
        .subquery()
    )
    return (
        select(EmailAiAnalysisModel, EmailConnectionModel)
        .join(
            ranked_claim_candidates,
            ranked_claim_candidates.c.analysis_id == EmailAiAnalysisModel.id,
        )
        .join(
            EmailConnectionModel,
            and_(
                EmailConnectionModel.id == EmailAiAnalysisModel.connection_id,
                EmailConnectionModel.agency_id == EmailAiAnalysisModel.agency_id,
                EmailConnectionModel.owner_user_id == EmailAiAnalysisModel.owner_user_id,
            ),
        )
        .order_by(
            ranked_claim_candidates.c.slot_order.asc(),
            ranked_claim_candidates.c.starved_received_at.asc(),
            ranked_claim_candidates.c.message_received_at.desc(),
            EmailAiAnalysisModel.id.desc(),
        )
        .limit(claim_limit)
        .with_for_update(skip_locked=True, of=EmailAiAnalysisModel)
    )
