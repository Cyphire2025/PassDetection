"""Finalize a validated claim under rollout lock with transactional result staging."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.config.settings import Settings
from app.core.logging.logger import get_logger
from app.domain.value_objects.email_ai_analysis import (
    EmailAnalysisProviderStatus,
    EmailAnalysisResult,
    EmailRelevance,
)
from app.infrastructure.email.ai_claim import EmailAiClaim
from app.infrastructure.email.ai_context import EmailAiContext
from app.infrastructure.email.ai_link_policy import (
    _authorized_context_group_name,
    _candidate_links_are_ambiguous,
    _canonical_link_ids,
)
from app.infrastructure.email.ai_notifications import _record_analysis_activity
from app.infrastructure.email.ai_result_records import (
    stage_deadlines,
    stage_proposals,
    stage_reply_draft,
)
from app.infrastructure.email.ai_runtime_dependencies import PersistenceDependencies
from app.infrastructure.email.ai_values import _manual_retry_generation, _pause_loaded_analysis
from app.infrastructure.email.deadline_notifications import mark_initial_deadline_window_coverage

logger = get_logger("app.infrastructure.email.ai_runtime")


async def _persist_analysis_result(
    claim: EmailAiClaim,
    *,
    context: EmailAiContext,
    result: EmailAnalysisResult,
    duration_ms: int,
    settings: Settings,
    dependencies: PersistenceDependencies,
) -> None:
    async with dependencies.session_factory() as session:
        row = await dependencies.load_valid_claim(session, claim, for_update=True)
        if row is None:
            logger.warning(
                "email_ai_result_discarded",
                analysis_id=str(claim.analysis_id),
                reason="stale_claim",
            )
            return
        analysis, message, connection = row
        if not await dependencies.policy_allows(
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
        safe_result["evidence"] = [link.rationale for link in result.candidate_links][:30]
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
        persisted_deadlines = stage_deadlines(
            session,
            analysis=analysis,
            result=result,
            settings=settings,
            operational_result=operational_result,
        )
        proposal_count = stage_proposals(
            session,
            analysis=analysis,
            result=result,
            context=context,
            operational_result=operational_result,
        )
        draft = stage_reply_draft(
            session,
            analysis=analysis,
            message=message,
            result=result,
            operational_result=operational_result,
        )

        await _record_analysis_activity(
            session,
            analysis=analysis,
            result=result,
        )
        await session.flush()
        if settings.email_ai_notifications_ready:
            await dependencies.create_attention_notification(
                session,
                analysis=analysis,
                message=message,
                connection=connection,
                result=result,
                deadlines=persisted_deadlines,
                draft=draft,
                proposal_count=proposal_count,
                notification_window_days=(settings.email_ai_deadline_notification_window_days),
                linked_group_name=linked_group_name,
            )
            await mark_initial_deadline_window_coverage(
                session,
                rows=[
                    (deadline, analysis, message, connection) for deadline in persisted_deadlines
                ],
                now=datetime.now(tz=UTC),
                window_days=(settings.email_ai_deadline_notification_window_days),
            )
        await session.commit()
