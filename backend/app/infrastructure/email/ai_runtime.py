"""Durable email-AI orchestration with explicit call-time persistence boundaries."""

from __future__ import annotations

import asyncio
import uuid as uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.email_integrations.analysis_contract import (
    EMAIL_AI_SCHEMA_VERSION as EMAIL_AI_SCHEMA_VERSION,
)
from app.application.use_cases.email_integrations.rollout_policy import email_ai_policy_allows
from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import UserRole
from app.domain.value_objects.email_ai_analysis import (
    EmailAnalysisProviderStatus,
    EmailAnalysisResult,
)
from app.infrastructure.ai.gemini_email_analysis_service import GeminiEmailAnalysisService
from app.infrastructure.ai_priority import (
    AdmissionStatus,
    AiPriorityCoordinator,
    MaintainPriorityLease,
    get_ai_priority_coordinator,
)
from app.infrastructure.database.email_ai_models import (
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import EmailConnectionModel, EmailMessageModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.email import ai_claim_lifecycle as _lifecycle
from app.infrastructure.email import ai_claim_repository as _claim_repository
from app.infrastructure.email import ai_dispatch as _dispatch
from app.infrastructure.email import ai_notifications as _notifications
from app.infrastructure.email import ai_persistence as _persistence
from app.infrastructure.email.ai_claim import EmailAiClaim as EmailAiClaim
from app.infrastructure.email.ai_context import EmailAiContext, load_email_ai_context
from app.infrastructure.email.ai_link_policy import (
    _authorized_context_group_name as _authorized_context_group_name,
)
from app.infrastructure.email.ai_link_policy import (
    _candidate_fact as _candidate_fact,
)
from app.infrastructure.email.ai_link_policy import (
    _candidate_links_are_ambiguous as _candidate_links_are_ambiguous,
)
from app.infrastructure.email.ai_link_policy import (
    _canonical_link_ids as _canonical_link_ids,
)
from app.infrastructure.email.ai_notifications import (
    _record_analysis_activity as _record_analysis_activity,
)
from app.infrastructure.email.ai_runtime_dependencies import (
    ClaimDependencies,
    PersistenceDependencies,
)
from app.infrastructure.email.ai_values import (
    _aware_utc as _aware_utc,
)
from app.infrastructure.email.ai_values import (
    _manual_retry_generation as _manual_retry_generation,
)
from app.infrastructure.email.ai_values import (
    _pause_loaded_analysis as _pause_loaded_analysis,
)
from app.infrastructure.email.ai_values import (
    _safe_reply_address as _safe_reply_address,
)
from app.infrastructure.email.ai_values import (
    _seed_input_hash as _seed_input_hash,
)
from app.infrastructure.repositories.notification_repository import NotificationRepository

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


def _claim_dependencies() -> ClaimDependencies:
    return ClaimDependencies(AsyncSessionFactory, _load_valid_claim, NotificationRepository)


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
            deadline_confidence_threshold=(settings.email_ai_deadline_confidence_threshold),
        )
        result = await service.analyze(context.request)
        duration_ms = max(
            0,
            int((datetime.now(tz=UTC) - started_at).total_seconds() * 1000),
        )
        if result.provider_status in {
            EmailAnalysisProviderStatus.TIMEOUT,
            EmailAnalysisProviderStatus.PROVIDER_UNAVAILABLE,
        } and await _retry_transient_failure(
            claim,
            result=result,
            settings=settings,
        ):
            return
        await _persist_analysis_result(
            claim,
            context=context,
            result=result,
            duration_ms=duration_ms,
            settings=settings,
        )


async def _load_valid_claim(
    session: AsyncSession,
    claim: EmailAiClaim,
    *,
    for_update: bool,
) -> (
    tuple[
        EmailAiAnalysisModel,
        EmailMessageModel,
        EmailConnectionModel,
    ]
    | None
):
    return await _claim_repository._load_valid_claim(
        session,
        claim,
        for_update=for_update,
        office_roles=_OFFICE_ROLES,
        settled_statuses=_SETTLED_MESSAGE_PROCESSING_STATUSES,
    )


async def seed_and_claim_email_ai_work(
    settings: Settings | None = None,
) -> list[EmailAiClaim]:
    return await _dispatch.seed_and_claim_work(
        settings or get_settings(),
        session_factory=AsyncSessionFactory,
        seed_input_hash=_seed_input_hash,
        dispatch_batch_size=_DISPATCH_BATCH_SIZE,
        per_owner_seed_limit=_PER_OWNER_SEED_LIMIT,
        per_owner_claim_limit=_PER_OWNER_CLAIM_LIMIT,
        claim_starvation_age=_CLAIM_STARVATION_AGE,
        office_roles=_OFFICE_ROLES,
        settled_statuses=_SETTLED_MESSAGE_PROCESSING_STATUSES,
    )


async def _defer_for_ai_priority(
    claim: EmailAiClaim,
    *,
    retry_after_ms: int,
) -> None:
    return await _lifecycle._defer_for_ai_priority(
        claim, retry_after_ms=retry_after_ms, dependencies=_claim_dependencies()
    )


async def release_email_ai_claim_after_error(
    claim: EmailAiClaim,
    *,
    settings: Settings | None = None,
) -> None:
    return await _lifecycle.release_email_ai_claim_after_error(
        claim, settings=settings or get_settings(), dependencies=_claim_dependencies()
    )


async def release_email_ai_claim_after_publish_failure(
    claim: EmailAiClaim,
) -> None:
    return await _lifecycle.release_email_ai_claim_after_publish_failure(
        claim, dependencies=_claim_dependencies()
    )


async def _retry_transient_failure(
    claim: EmailAiClaim,
    *,
    result: EmailAnalysisResult,
    settings: Settings,
) -> bool:
    return await _lifecycle._retry_transient_failure(
        claim, result=result, settings=settings, dependencies=_claim_dependencies()
    )


async def _finish_without_analysis(
    claim: EmailAiClaim,
    *,
    status: str,
    error_code: str,
) -> None:
    return await _lifecycle._finish_without_analysis(
        claim, status=status, error_code=error_code, dependencies=_claim_dependencies()
    )


async def _pause_claim_for_policy(
    claim: EmailAiClaim,
    *,
    error_code: str,
) -> None:
    return await _lifecycle._pause_claim_for_policy(
        claim, error_code=error_code, dependencies=_claim_dependencies()
    )


async def _persist_analysis_result(
    claim: EmailAiClaim,
    *,
    context: EmailAiContext,
    result: EmailAnalysisResult,
    duration_ms: int,
    settings: Settings,
) -> None:
    return await _persistence._persist_analysis_result(
        claim,
        context=context,
        result=result,
        duration_ms=duration_ms,
        settings=settings,
        dependencies=PersistenceDependencies(
            AsyncSessionFactory,
            _load_valid_claim,
            email_ai_policy_allows,
            _create_attention_notification,
        ),
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
    return await _notifications._create_attention_notification(
        session,
        analysis=analysis,
        message=message,
        connection=connection,
        result=result,
        deadlines=deadlines,
        draft=draft,
        proposal_count=proposal_count,
        notification_window_days=notification_window_days,
        linked_group_name=linked_group_name,
        notification_repository=NotificationRepository,
    )
