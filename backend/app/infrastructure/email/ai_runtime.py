"""Durable runtime for owner-scoped travel email analysis."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.email_integrations.analysis_contract import (
    EMAIL_AI_SCHEMA_VERSION,
)
from app.application.use_cases.email_integrations.rollout_policy import (
    email_ai_disabled_policy_exists,
    email_ai_policy_allows,
)
from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import UserRole
from app.domain.value_objects.email_ai_analysis import (
    ActionDisposition,
    DeadlineResolutionStatus,
    EmailAnalysisProviderStatus,
    EmailAnalysisResult,
    EmailRelevance,
)
from app.infrastructure.ai.gemini_email_analysis_service import (
    GeminiEmailAnalysisService,
)
from app.infrastructure.ai_priority import (
    AdmissionStatus,
    AiPriorityCoordinator,
    MaintainPriorityLease,
    get_ai_priority_coordinator,
)
from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailConnectionModel,
    EmailMessageModel,
)
from app.infrastructure.database.models import UserModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.email.ai_context import EmailAiContext, load_email_ai_context
from app.infrastructure.email.deadline_notifications import (
    mark_initial_deadline_window_coverage,
)
from app.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)

logger = get_logger(__name__)

_DISPATCH_BATCH_SIZE = 50
_PER_OWNER_SEED_LIMIT = 2
_PER_OWNER_CLAIM_LIMIT = 2
_CLAIM_STARVATION_AGE = timedelta(minutes=15)
_SETTLED_MESSAGE_PROCESSING_STATUSES = {
    "completed",
    "partially_completed",
    "review_required",
    "failed",
    "ignored",
}
_OFFICE_ROLES = {
    UserRole.SUPER_ADMIN.value,
    UserRole.AGENCY_ADMIN.value,
    UserRole.AGENCY_MANAGER.value,
    UserRole.AGENCY_STAFF.value,
}


@dataclass(frozen=True)
class EmailAiClaim:
    analysis_id: uuid.UUID
    agency_id: uuid.UUID
    owner_user_id: uuid.UUID
    connection_id: uuid.UUID
    message_id: uuid.UUID
    provider_account_id: str
    sync_generation: int
    lease_token: str

    def task_kwargs(self) -> dict[str, object]:
        return {
            "analysis_id": str(self.analysis_id),
            "agency_id": str(self.agency_id),
            "owner_user_id": str(self.owner_user_id),
            "connection_id": str(self.connection_id),
            "message_id": str(self.message_id),
            "provider_account_id": self.provider_account_id,
            "sync_generation": self.sync_generation,
            "lease_token": self.lease_token,
        }


async def seed_and_claim_email_ai_work(
    settings: Settings | None = None,
) -> list[EmailAiClaim]:
    settings = settings or get_settings()
    if not settings.email_ai_runtime_ready:
        return []
    now = datetime.now(tz=UTC)
    async with AsyncSessionFactory() as session:
        ranked_seed_candidates = (
            select(
                EmailMessageModel.id.label("message_id"),
                EmailMessageModel.received_at.label(
                    "message_received_at"
                ),
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
                            EmailMessageModel.received_at
                            <= now - _CLAIM_STARVATION_AGE,
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
                    EmailConnectionModel.owner_user_id
                    == EmailMessageModel.owner_user_id,
                ),
            )
            .join(UserModel, UserModel.id == EmailMessageModel.owner_user_id)
            .where(
                EmailMessageModel.processing_status.in_(
                    _SETTLED_MESSAGE_PROCESSING_STATUSES
                ),
                EmailMessageModel.relevance_status != "failed",
                EmailMessageModel.evidence_json[
                    "human_marked_unrelated"
                ].as_boolean().is_not(True),
                EmailConnectionModel.status.in_({"active", "failing"}),
                EmailConnectionModel.ai_processing_enabled.is_(True),
                EmailConnectionModel.ai_enabled_at.is_not(None),
                EmailMessageModel.received_at >= EmailConnectionModel.ai_enabled_at,
                UserModel.is_active.is_(True),
                UserModel.role.in_(_OFFICE_ROLES),
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
                        EmailAiAnalysisModel.owner_user_id
                        == EmailMessageModel.owner_user_id,
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
                        ranked_seed_candidates.c.newest_rank
                        <= _PER_OWNER_SEED_LIMIT,
                    ),
                )
            )
            .subquery()
        )
        seed_result = await session.execute(
            select(EmailMessageModel, EmailConnectionModel)
            .join(
                prioritized_seed_candidates,
                prioritized_seed_candidates.c.message_id
                == EmailMessageModel.id,
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
            .limit(_DISPATCH_BATCH_SIZE)
            .with_for_update(skip_locked=True, of=EmailMessageModel)
        )
        for message, connection in seed_result.all():
            session.add(
                EmailAiAnalysisModel(
                    agency_id=message.agency_id,
                    owner_user_id=message.owner_user_id,
                    connection_id=message.connection_id,
                    message_id=message.id,
                    status="pending",
                    input_hash=_seed_input_hash(message),
                    prompt_schema_version=EMAIL_AI_SCHEMA_VERSION,
                    config_version=settings.gemini_config_version,
                    ai_model=settings.gemini_model,
                )
            )
        await session.flush()

        active_claim_count = int(
            await session.scalar(
                select(func.count(EmailAiAnalysisModel.id)).where(
                    EmailAiAnalysisModel.status == "processing",
                    EmailAiAnalysisModel.lease_expires_at > now,
                )
            )
            or 0
        )
        claim_limit = max(
            0,
            settings.email_ai_max_inflight - active_claim_count,
        )
        if claim_limit == 0:
            await session.commit()
            return []

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
                            EmailMessageModel.received_at
                            <= now - _CLAIM_STARVATION_AGE,
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
                    EmailMessageModel.id
                    == EmailAiAnalysisModel.message_id,
                    EmailMessageModel.connection_id
                    == EmailAiAnalysisModel.connection_id,
                    EmailMessageModel.agency_id
                    == EmailAiAnalysisModel.agency_id,
                    EmailMessageModel.owner_user_id
                    == EmailAiAnalysisModel.owner_user_id,
                ),
            )
            .join(
                EmailConnectionModel,
                and_(
                    EmailConnectionModel.id == EmailAiAnalysisModel.connection_id,
                    EmailConnectionModel.agency_id == EmailAiAnalysisModel.agency_id,
                    EmailConnectionModel.owner_user_id
                    == EmailAiAnalysisModel.owner_user_id,
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
                EmailAiAnalysisModel.attempt_count < settings.email_ai_max_attempts,
                EmailMessageModel.processing_status.in_(
                    _SETTLED_MESSAGE_PROCESSING_STATUSES
                ),
                EmailMessageModel.relevance_status != "failed",
                EmailMessageModel.evidence_json[
                    "human_marked_unrelated"
                ].as_boolean().is_not(True),
                EmailConnectionModel.status.in_({"active", "failing"}),
                EmailConnectionModel.ai_processing_enabled.is_(True),
                EmailConnectionModel.ai_enabled_at.is_not(None),
                EmailMessageModel.received_at
                >= EmailConnectionModel.ai_enabled_at,
                UserModel.is_active.is_(True),
                UserModel.role.in_(_OFFICE_ROLES),
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
                        eligible_claims.c.newest_rank
                        <= _PER_OWNER_CLAIM_LIMIT,
                    ),
                )
            )
            .subquery()
        )
        claim_result = await session.execute(
            select(EmailAiAnalysisModel, EmailConnectionModel)
            .join(
                ranked_claim_candidates,
                ranked_claim_candidates.c.analysis_id
                == EmailAiAnalysisModel.id,
            )
            .join(
                EmailConnectionModel,
                and_(
                    EmailConnectionModel.id == EmailAiAnalysisModel.connection_id,
                    EmailConnectionModel.agency_id == EmailAiAnalysisModel.agency_id,
                    EmailConnectionModel.owner_user_id
                    == EmailAiAnalysisModel.owner_user_id,
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
        claims: list[EmailAiClaim] = []
        for analysis, connection in claim_result.all():
            lease_token = uuid.uuid4().hex
            analysis.status = "processing"
            analysis.lease_token = lease_token
            analysis.lease_expires_at = now + timedelta(
                seconds=settings.email_ai_lease_seconds
            )
            analysis.next_attempt_at = None
            analysis.attempt_count += 1
            analysis.started_at = now
            claims.append(
                EmailAiClaim(
                    analysis_id=analysis.id,
                    agency_id=analysis.agency_id,
                    owner_user_id=analysis.owner_user_id,
                    connection_id=analysis.connection_id,
                    message_id=analysis.message_id,
                    provider_account_id=connection.provider_account_id,
                    sync_generation=connection.sync_generation,
                    lease_token=lease_token,
                )
            )
        await session.commit()
        return claims


async def run_email_ai_claim(
    claim: EmailAiClaim,
    settings: Settings | None = None,
    *,
    priority_coordinator: AiPriorityCoordinator | None = None,
) -> None:
    settings = settings or get_settings()
    if not settings.email_ai_runtime_ready:
        return
    started_at = datetime.now(tz=UTC)
    async with AsyncSessionFactory() as session:
        row = await _load_valid_claim(session, claim, for_update=False)
        if row is None:
            logger.warning(
                "email_ai_claim_rejected",
                analysis_id=str(claim.analysis_id),
                reason="context_mismatch",
            )
            return
        analysis, message, connection = row
        if not await email_ai_policy_allows(
            session,
            agency_id=claim.agency_id,
            owner_user_id=claim.owner_user_id,
            connection_id=claim.connection_id,
        ):
            await _pause_claim_for_policy(
                claim,
                error_code="rollout_policy_disabled",
            )
            return
        context = await load_email_ai_context(
            session,
            message=message,
            agency_id=claim.agency_id,
            owner_user_id=claim.owner_user_id,
            connected_account_email=connection.email_address,
            timezone_name=settings.email_ai_default_timezone,
            max_input_chars=settings.email_ai_max_input_chars,
            max_candidates=settings.email_ai_max_candidates,
        )
        if context is None:
            await _finish_without_analysis(
                claim,
                status="failed",
                error_code="owner_context_unavailable",
            )
            return
        analysis.input_hash = context.input_hash
        analysis.context_manifest = context.manifest
        await session.commit()

    priority = priority_coordinator or get_ai_priority_coordinator()
    decision = await asyncio.to_thread(
        priority.try_start_verification,
        f"email-ai:{claim.analysis_id}",
    )
    if not decision.admitted:
        if decision.status not in {
            AdmissionStatus.DUPLICATE,
            AdmissionStatus.STALE,
        }:
            await _defer_for_ai_priority(
                claim,
                retry_after_ms=decision.retry_after_ms,
            )
        return

    async with MaintainPriorityLease(priority, decision.lease):
        service = GeminiEmailAnalysisService(
            api_key=settings.google_api_key,
            model=settings.gemini_model,
            timeout_seconds=settings.email_ai_analysis_timeout_seconds,
            api_base_url=settings.gemini_api_base_url,
            max_output_tokens=settings.email_ai_max_output_tokens,
            review_confidence_threshold=settings.email_ai_auto_confidence_threshold,
            deadline_confidence_threshold=(
                settings.email_ai_deadline_confidence_threshold
            ),
        )
        result = await service.analyze(context.request)
        duration_ms = max(
            0,
            int((datetime.now(tz=UTC) - started_at).total_seconds() * 1000),
        )
        if (
            result.provider_status
            in {
                EmailAnalysisProviderStatus.TIMEOUT,
                EmailAnalysisProviderStatus.PROVIDER_UNAVAILABLE,
            }
            and await _retry_transient_failure(
                claim,
                result=result,
                settings=settings,
            )
        ):
            return
        await _persist_analysis_result(
            claim,
            context=context,
            result=result,
            duration_ms=duration_ms,
            settings=settings,
        )


async def _defer_for_ai_priority(
    claim: EmailAiClaim,
    *,
    retry_after_ms: int,
) -> None:
    """Release a capacity-deferred claim without consuming its attempt budget."""

    delay_seconds = min(300, max(1, math.ceil(retry_after_ms / 1_000)))
    async with AsyncSessionFactory() as session:
        row = await _load_valid_claim(session, claim, for_update=True)
        if row is None:
            return
        analysis, _, _ = row
        analysis.status = "pending"
        analysis.attempt_count = max(0, analysis.attempt_count - 1)
        analysis.last_error_code = "ai_priority_admission_deferred"
        analysis.lease_token = None
        analysis.lease_expires_at = None
        analysis.next_attempt_at = datetime.now(tz=UTC) + timedelta(
            seconds=delay_seconds
        )
        analysis.started_at = None
        analysis.completed_at = None
        await session.commit()


async def release_email_ai_claim_after_error(
    claim: EmailAiClaim,
    *,
    settings: Settings | None = None,
) -> None:
    """Release a claimed row after an unexpected worker failure."""

    settings = settings or get_settings()
    async with AsyncSessionFactory() as session:
        row = await _load_valid_claim(session, claim, for_update=True)
        if row is None:
            return
        analysis, message, connection = row
        analysis.last_error_code = "unexpected_runtime_error"
        analysis.lease_token = None
        analysis.lease_expires_at = None
        if analysis.attempt_count < settings.email_ai_max_attempts:
            analysis.status = "pending"
            analysis.next_attempt_at = datetime.now(tz=UTC) + timedelta(seconds=30)
        else:
            analysis.status = "failed"
            analysis.needs_attention = True
            analysis.completed_at = datetime.now(tz=UTC)
            analysis.next_attempt_at = None
            if settings.email_ai_notifications_ready:
                await NotificationRepository(session).create(
                    agency_id=analysis.agency_id,
                    user_id=analysis.owner_user_id,
                    type="email_ai_failure",
                    title="Travel email analysis needs attention",
                    message=(
                        "Automated analysis could not be completed after retrying. "
                        "The synchronized email remains available for manual review."
                    ),
                    entity_type="email_message",
                    entity_id=str(message.id),
                    priority="high",
                    category="email_operations",
                    dedupe_key=(
                        f"email-ai:{analysis.id}:persistent-failure:"
                        f"{_manual_retry_generation(analysis)}"
                    ),
                    metadata={
                        "provider": connection.provider,
                        "account_email": connection.email_address,
                        "analysis_id": str(analysis.id),
                    },
                )
        await session.commit()


async def release_email_ai_claim_after_publish_failure(
    claim: EmailAiClaim,
) -> None:
    """Release broker-undelivered work without spending a provider attempt."""

    async with AsyncSessionFactory() as session:
        row = await _load_valid_claim(session, claim, for_update=True)
        if row is None:
            return
        analysis, _, _ = row
        analysis.status = "pending"
        analysis.attempt_count = max(0, analysis.attempt_count - 1)
        analysis.last_error_code = "broker_publish_failed"
        analysis.lease_token = None
        analysis.lease_expires_at = None
        analysis.next_attempt_at = datetime.now(tz=UTC) + timedelta(seconds=5)
        analysis.started_at = None
        analysis.completed_at = None
        await session.commit()


async def _load_valid_claim(
    session: AsyncSession,
    claim: EmailAiClaim,
    *,
    for_update: bool,
) -> tuple[
    EmailAiAnalysisModel,
    EmailMessageModel,
    EmailConnectionModel,
] | None:
    statement = (
        select(EmailAiAnalysisModel, EmailMessageModel, EmailConnectionModel)
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
                EmailConnectionModel.owner_user_id
                == EmailAiAnalysisModel.owner_user_id,
            ),
        )
        .join(UserModel, UserModel.id == EmailAiAnalysisModel.owner_user_id)
        .where(
            EmailAiAnalysisModel.id == claim.analysis_id,
            EmailAiAnalysisModel.agency_id == claim.agency_id,
            EmailAiAnalysisModel.owner_user_id == claim.owner_user_id,
            EmailAiAnalysisModel.connection_id == claim.connection_id,
            EmailAiAnalysisModel.message_id == claim.message_id,
            EmailAiAnalysisModel.status == "processing",
            EmailAiAnalysisModel.lease_token == claim.lease_token,
            EmailConnectionModel.provider_account_id == claim.provider_account_id,
            EmailConnectionModel.sync_generation == claim.sync_generation,
            EmailConnectionModel.ai_processing_enabled.is_(True),
            EmailConnectionModel.ai_enabled_at.is_not(None),
            EmailMessageModel.received_at >= EmailConnectionModel.ai_enabled_at,
            EmailMessageModel.processing_status.in_(
                _SETTLED_MESSAGE_PROCESSING_STATUSES
            ),
            EmailMessageModel.relevance_status != "failed",
            EmailMessageModel.evidence_json[
                "human_marked_unrelated"
            ].as_boolean().is_not(True),
            UserModel.is_active.is_(True),
            UserModel.role.in_(_OFFICE_ROLES),
            or_(
                UserModel.role == UserRole.SUPER_ADMIN.value,
                UserModel.agency_id == EmailAiAnalysisModel.agency_id,
            ),
        )
    )
    if for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return result.tuples().one_or_none()


async def _persist_analysis_result(
    claim: EmailAiClaim,
    *,
    context: EmailAiContext,
    result: EmailAnalysisResult,
    duration_ms: int,
    settings: Settings,
) -> None:
    async with AsyncSessionFactory() as session:
        row = await _load_valid_claim(session, claim, for_update=True)
        if row is None:
            logger.warning(
                "email_ai_result_discarded",
                analysis_id=str(claim.analysis_id),
                reason="stale_claim",
            )
            return
        analysis, message, connection = row
        if not await email_ai_policy_allows(
            session,
            agency_id=claim.agency_id,
            owner_user_id=claim.owner_user_id,
            connection_id=claim.connection_id,
            lock_namespace=True,
        ):
            _pause_loaded_analysis(
                analysis,
                error_code="rollout_policy_disabled_during_analysis",
            )
            await session.commit()
            return
        if result.provider_status == EmailAnalysisProviderStatus.ANALYZED:
            if result.relevance == EmailRelevance.UNRELATED:
                analysis.status = "ignored"
            elif result.needs_review:
                analysis.status = "review_required"
            else:
                analysis.status = "completed"
        elif result.provider_status == EmailAnalysisProviderStatus.INVALID_RESPONSE:
            analysis.status = "review_required"
        else:
            analysis.status = "failed"

        linked_group_id, linked_passenger_ids = _canonical_link_ids(
            context=context,
            result=result,
            confidence_threshold=settings.email_ai_auto_confidence_threshold,
        )
        linked_group_name = _authorized_context_group_name(
            context,
            linked_group_id,
        )

        safe_result = result.model_dump(
            mode="json",
            exclude={"reply_draft", "proposals"},
        )
        retry_generation = _manual_retry_generation(analysis)
        safe_result["manual_retry_generation"] = retry_generation
        safe_result["linked_group_id"] = (
            str(linked_group_id) if linked_group_id is not None else None
        )
        safe_result["linked_passenger_ids"] = linked_passenger_ids
        safe_result["candidate_ambiguity"] = _candidate_links_are_ambiguous(
            context=context,
            result=result,
        )
        safe_result["evidence"] = [
            link.rationale for link in result.candidate_links
        ][:30]
        analysis.intent = result.intent.value
        analysis.priority = result.priority.value
        analysis.summary = result.summary
        analysis.confidence = result.confidence
        analysis.needs_attention = result.needs_review
        analysis.ai_model = result.model
        analysis.result_json = safe_result
        analysis.last_error_code = result.reason_code
        analysis.completed_at = datetime.now(tz=UTC)
        analysis.duration_ms = duration_ms
        analysis.lease_token = None
        analysis.lease_expires_at = None
        analysis.next_attempt_at = None

        operational_result = result.relevance != EmailRelevance.UNRELATED
        persisted_deadlines: list[EmailDetectedDeadlineModel] = []
        deadline_fingerprints: set[str] = set()
        for deadline in result.deadlines if operational_result else []:
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "source_text": deadline.source_text,
                        "expression": deadline.expression,
                        "due_at": (
                            deadline.due_at.isoformat()
                            if deadline.due_at is not None
                            else None
                        ),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if fingerprint in deadline_fingerprints:
                continue
            deadline_fingerprints.add(fingerprint)
            deadline_row = EmailDetectedDeadlineModel(
                agency_id=analysis.agency_id,
                owner_user_id=analysis.owner_user_id,
                connection_id=analysis.connection_id,
                message_id=analysis.message_id,
                analysis_id=analysis.id,
                deadline_type="response_due",
                source_phrase=deadline.source_text,
                source_fingerprint=fingerprint,
                source_timezone=settings.email_ai_default_timezone,
                due_at=deadline.due_at,
                confidence=deadline.confidence,
                is_ambiguous=(
                    deadline.status == DeadlineResolutionStatus.REVIEW_REQUIRED
                ),
                status=(
                    "review_required"
                    if deadline.status == DeadlineResolutionStatus.REVIEW_REQUIRED
                    else "detected"
                ),
                resolution_evidence={"reason_code": deadline.reason_code},
            )
            session.add(deadline_row)
            persisted_deadlines.append(deadline_row)

        decisions_by_index = list(result.action_decisions)
        proposal_idempotency_keys: set[str] = set()
        for index, proposal in enumerate(
            result.proposals if operational_result else []
        ):
            decision = decisions_by_index[index]
            target = (
                context.aliases.get(proposal.target_alias)
                if proposal.target_alias is not None
                else None
            )
            payload: dict[str, object] = {
                "target_alias": proposal.target_alias,
                "deadline_expression": proposal.deadline_expression,
            }
            if target is not None:
                payload["target_entity_type"] = target[0]
                payload["target_entity_id"] = str(target[1])
            idempotency_key = hashlib.sha256(
                json.dumps(
                    {
                        "analysis_id": str(analysis.id),
                        "action": proposal.action.value,
                        "payload": payload,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if idempotency_key in proposal_idempotency_keys:
                continue
            proposal_idempotency_keys.add(idempotency_key)
            session.add(
                EmailActionProposalModel(
                    agency_id=analysis.agency_id,
                    owner_user_id=analysis.owner_user_id,
                    connection_id=analysis.connection_id,
                    message_id=analysis.message_id,
                    analysis_id=analysis.id,
                    action_type=proposal.action.value,
                    risk_level=decision.risk_level.value,
                    status=(
                        "blocked"
                        if decision.disposition == ActionDisposition.BLOCKED
                        else "approval_required"
                    ),
                    explanation=proposal.rationale,
                    payload_json=payload,
                    confidence=proposal.confidence,
                    requires_approval=(
                        decision.disposition == ActionDisposition.PROPOSAL_ONLY
                    ),
                    idempotency_key=idempotency_key,
                )
            )

        draft: EmailReplyDraftModel | None = None
        if result.reply_draft is not None and operational_result:
            reply_address = _safe_reply_address(message.sender_address)
            recipients = [reply_address] if reply_address is not None else []
            draft = EmailReplyDraftModel(
                agency_id=analysis.agency_id,
                owner_user_id=analysis.owner_user_id,
                connection_id=analysis.connection_id,
                message_id=analysis.message_id,
                analysis_id=analysis.id,
                recipients_json=recipients,
                subject=result.reply_draft.subject,
                body_text=result.reply_draft.body,
                status="prepared",
            )
            session.add(draft)

        await _record_analysis_activity(
            session,
            analysis=analysis,
            result=result,
        )
        await session.flush()
        if settings.email_ai_notifications_ready:
            await _create_attention_notification(
                session,
                analysis=analysis,
                message=message,
                connection=connection,
                result=result,
                deadlines=persisted_deadlines,
                draft=draft,
                proposal_count=len(proposal_idempotency_keys),
                notification_window_days=(
                    settings.email_ai_deadline_notification_window_days
                ),
                linked_group_name=linked_group_name,
            )
            await mark_initial_deadline_window_coverage(
                session,
                rows=[
                    (deadline, analysis, message, connection)
                    for deadline in persisted_deadlines
                ],
                now=datetime.now(tz=UTC),
                window_days=(
                    settings.email_ai_deadline_notification_window_days
                ),
            )
        await session.commit()


def _canonical_link_ids(
    *,
    context: EmailAiContext,
    result: EmailAnalysisResult,
    confidence_threshold: float,
) -> tuple[uuid.UUID | None, list[str]]:
    """Persist canonical links only when provider candidates are unambiguous."""

    group_ids: list[uuid.UUID] = []
    linked_group_aliases: list[str] = []
    passenger_ids: list[str] = []
    linked_passenger_aliases: list[str] = []
    for link in result.candidate_links:
        if link.confidence < confidence_threshold:
            continue
        entity = context.aliases.get(link.alias)
        if entity is None:
            continue
        entity_type, entity_id = entity
        if entity_type == "group" and entity_id not in group_ids:
            group_ids.append(entity_id)
            linked_group_aliases.append(link.alias)
        elif entity_type == "passenger":
            passenger_id = str(entity_id)
            if passenger_id not in passenger_ids:
                passenger_ids.append(passenger_id)
                linked_passenger_aliases.append(link.alias)

    if len(group_ids) > 1:
        return None, []

    candidates = {
        candidate.alias: candidate for candidate in context.request.visible_candidates
    }
    selected_group_alias = (
        linked_group_aliases[0] if len(linked_group_aliases) == 1 else None
    )
    passenger_parent_aliases: set[str] = set()
    passenger_names: list[str] = []
    for alias in linked_passenger_aliases:
        candidate = candidates.get(alias)
        if candidate is None:
            continue
        parent_alias = _candidate_fact(candidate.safe_facts, "group alias")
        if parent_alias:
            passenger_parent_aliases.add(parent_alias)
        name_fact = next(
            (
                fact.removeprefix("name:").strip().casefold()
                for fact in candidate.safe_facts
                if fact.casefold().startswith("name:")
            ),
            "",
        )
        if name_fact:
            passenger_names.append(name_fact)
    parent_mismatch = bool(
        selected_group_alias is not None
        and any(
            parent_alias != selected_group_alias
            for parent_alias in passenger_parent_aliases
        )
    )
    if (
        len(passenger_names) != len(set(passenger_names))
        or len(passenger_parent_aliases) > 1
        or parent_mismatch
    ):
        passenger_ids = []

    canonical_group_id = group_ids[0] if len(group_ids) == 1 else None
    if (
        canonical_group_id is None
        and len(passenger_parent_aliases) == 1
    ):
        parent_alias = next(iter(passenger_parent_aliases))
        parent_entity = context.aliases.get(parent_alias)
        if parent_entity is not None and parent_entity[0] == "group":
            canonical_group_id = parent_entity[1]
    return canonical_group_id, passenger_ids


def _authorized_context_group_name(
    context: EmailAiContext,
    linked_group_id: uuid.UUID | None,
) -> str | None:
    """Return a bounded group name only from the owner's authorized context."""

    if linked_group_id is None:
        return None
    group_alias = next(
        (
            alias
            for alias, (entity_type, entity_id) in context.aliases.items()
            if entity_type == "group" and entity_id == linked_group_id
        ),
        None,
    )
    if group_alias is None:
        return None
    candidate = next(
        (
            item
            for item in context.request.visible_candidates
            if item.alias == group_alias
        ),
        None,
    )
    if candidate is None:
        return None
    for fact in candidate.safe_facts:
        label, separator, value = fact.partition(":")
        if separator and label.strip().casefold() == "name":
            normalized = " ".join(value.split())[:160]
            return normalized or None
    return None


def _candidate_links_are_ambiguous(
    *,
    context: EmailAiContext,
    result: EmailAnalysisResult,
) -> bool:
    group_aliases: set[str] = set()
    for link in result.candidate_links:
        entity = context.aliases.get(link.alias)
        if entity is not None and entity[0] == "group":
            group_aliases.add(link.alias)
    if len(group_aliases) > 1:
        return True
    candidates = {
        candidate.alias: candidate for candidate in context.request.visible_candidates
    }
    selected_group_alias = next(iter(group_aliases), None)
    passenger_parent_aliases: set[str] = set()
    passenger_names: list[str] = []
    for link in result.candidate_links:
        entity = context.aliases.get(link.alias)
        if entity is None or entity[0] != "passenger":
            continue
        candidate = candidates.get(link.alias)
        if candidate is None:
            continue
        parent_alias = _candidate_fact(candidate.safe_facts, "group alias")
        if parent_alias:
            passenger_parent_aliases.add(parent_alias)
        name_fact = next(
            (
                fact.removeprefix("name:").strip().casefold()
                for fact in candidate.safe_facts
                if fact.casefold().startswith("name:")
            ),
            "",
        )
        if name_fact:
            passenger_names.append(name_fact)
    return bool(
        len(passenger_names) != len(set(passenger_names))
        or len(passenger_parent_aliases) > 1
        or (
            selected_group_alias is not None
            and any(
                parent_alias != selected_group_alias
                for parent_alias in passenger_parent_aliases
            )
        )
    )


def _candidate_fact(safe_facts: list[str], label: str) -> str | None:
    prefix = f"{label}:"
    for fact in safe_facts:
        if fact.casefold().startswith(prefix.casefold()):
            value = fact[len(prefix) :].strip()
            return value or None
    return None


async def _retry_transient_failure(
    claim: EmailAiClaim,
    *,
    result: EmailAnalysisResult,
    settings: Settings,
) -> bool:
    async with AsyncSessionFactory() as session:
        row = await _load_valid_claim(session, claim, for_update=True)
        if row is None:
            return True
        analysis, _, _ = row
        if analysis.attempt_count >= settings.email_ai_max_attempts:
            return False
        delay_seconds = min(300, 10 * (2 ** max(0, analysis.attempt_count - 1)))
        analysis.status = "pending"
        analysis.last_error_code = result.reason_code or result.provider_status.value
        analysis.lease_token = None
        analysis.lease_expires_at = None
        analysis.next_attempt_at = datetime.now(tz=UTC) + timedelta(
            seconds=delay_seconds
        )
        await session.commit()
        return True


async def _finish_without_analysis(
    claim: EmailAiClaim,
    *,
    status: str,
    error_code: str,
) -> None:
    async with AsyncSessionFactory() as session:
        row = await _load_valid_claim(session, claim, for_update=True)
        if row is None:
            return
        analysis, _, _ = row
        analysis.status = status
        analysis.last_error_code = error_code
        analysis.needs_attention = status == "failed"
        analysis.completed_at = datetime.now(tz=UTC)
        analysis.lease_token = None
        analysis.lease_expires_at = None
        await session.commit()


async def _pause_claim_for_policy(
    claim: EmailAiClaim,
    *,
    error_code: str,
) -> None:
    async with AsyncSessionFactory() as session:
        row = await _load_valid_claim(session, claim, for_update=True)
        if row is None:
            return
        analysis, _, _ = row
        _pause_loaded_analysis(analysis, error_code=error_code)
        await session.commit()


def _pause_loaded_analysis(
    analysis: EmailAiAnalysisModel,
    *,
    error_code: str,
) -> None:
    analysis.status = "pending"
    analysis.attempt_count = max(0, analysis.attempt_count - 1)
    analysis.last_error_code = error_code
    analysis.needs_attention = False
    analysis.lease_token = None
    analysis.lease_expires_at = None
    analysis.next_attempt_at = None
    analysis.started_at = None
    analysis.completed_at = None


async def _record_analysis_activity(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    result: EmailAnalysisResult,
) -> None:
    retry_generation = _manual_retry_generation(analysis)
    session.add(
        EmailActivityEventModel(
            agency_id=analysis.agency_id,
            owner_user_id=analysis.owner_user_id,
            connection_id=analysis.connection_id,
            message_id=analysis.message_id,
            event_key=(
                f"email-ai:{analysis.id}:completed:{retry_generation}"
            ),
            event_type="ai_analysis_completed",
            stage=(
                "warning"
                if analysis.status in {"review_required", "failed"}
                else "success"
            ),
            actor_type="system",
            summary_code=f"email_ai_{analysis.status}",
            details={
                "analysis_id": str(analysis.id),
                "provider_status": result.provider_status.value,
                "priority": result.priority.value,
                "needs_review": result.needs_review,
                "proposal_count": len(result.proposals),
                "deadline_count": len(result.deadlines),
                "retry_generation": retry_generation,
            },
            ai_used=True,
            ai_provider="google",
            ai_model=result.model,
            confidence=result.confidence,
            changed_entity_type="email_ai_analysis",
            changed_entity_id=analysis.id,
        )
    )


async def _create_attention_notification(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    message: EmailMessageModel,
    connection: EmailConnectionModel,
    result: EmailAnalysisResult,
    deadlines: list[EmailDetectedDeadlineModel],
    draft: EmailReplyDraftModel | None,
    proposal_count: int,
    notification_window_days: int,
    linked_group_name: str | None = None,
) -> None:
    high_risk = any(
        decision.risk_level.value in {"high", "critical"}
        for decision in result.action_decisions
    ) or any(risk.level.value in {"high", "critical"} for risk in result.risks)
    has_approval = any(
        decision.disposition == ActionDisposition.PROPOSAL_ONLY
        for decision in result.action_decisions
    )
    deadline_cutoff = datetime.now(tz=UTC) + timedelta(
        days=notification_window_days
    )
    actionable_deadlines = [
        deadline
        for deadline in deadlines
        if deadline.status == "review_required"
        or (
            deadline.due_at is not None
            and _aware_utc(deadline.due_at) <= deadline_cutoff
        )
    ]
    has_deadline = bool(actionable_deadlines)
    should_notify = (
        analysis.status == "failed"
        or result.needs_review
        or high_risk
        or has_approval
        or has_deadline
        or draft is not None
    )
    if not should_notify or result.relevance == EmailRelevance.UNRELATED:
        return
    priority = (
        "urgent"
        if high_risk or result.priority.value == "urgent"
        else "high"
        if result.needs_review
        or has_approval
        or result.priority.value == "high"
        else "normal"
    )
    if high_risk:
        title = "High-risk travel email needs review"
    elif has_approval:
        title = "Travel email action needs approval"
    elif has_deadline:
        title = "Travel deadline detected"
    elif draft is not None:
        title = "Prepared reply draft is ready"
    else:
        title = "Travel email needs attention"
    await NotificationRepository(session).create(
        agency_id=analysis.agency_id,
        user_id=analysis.owner_user_id,
        type="email_ai_attention",
        title=title,
        message=result.summary[:500],
        entity_type="email_message",
        entity_id=str(message.id),
        priority=priority,
        category="email_operations",
        dedupe_key=(
            f"email-ai:{analysis.id}:attention:"
            f"{_manual_retry_generation(analysis)}"
        ),
        metadata={
            "provider": connection.provider,
            "account_email": connection.email_address,
            "analysis_id": str(analysis.id),
            "deadline_count": len(actionable_deadlines),
            "proposal_count": proposal_count,
            "draft_ready": draft is not None,
            "retry_generation": _manual_retry_generation(analysis),
            **(
                {"group_name": linked_group_name}
                if linked_group_name is not None
                else {}
            ),
        },
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _manual_retry_generation(analysis: EmailAiAnalysisModel) -> int:
    value = (getattr(analysis, "result_json", None) or {}).get(
        "manual_retry_generation",
        0,
    )
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    ):
        return value
    return 0


def _seed_input_hash(message: EmailMessageModel) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "message_id": str(message.id),
                "provider_message_id": message.provider_message_id,
                "updated_at": message.updated_at.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _safe_reply_address(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if (
        not 3 <= len(normalized) <= 320
        or normalized.count("@") != 1
        or any(character.isspace() for character in normalized)
    ):
        return None
    local_part, domain = normalized.rsplit("@", 1)
    if not local_part or "." not in domain or domain.startswith(".") or domain.endswith("."):
        return None
    return normalized
