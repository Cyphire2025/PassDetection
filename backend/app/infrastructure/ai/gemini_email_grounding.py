"""Deterministic display, draft and deadline grounding against visible email facts."""

from __future__ import annotations

from app.application.use_cases.email_integrations.deadlines import resolve_deadline
from app.core.logging.logger import get_logger
from app.domain.value_objects.email_ai_analysis import (
    DeadlineResolutionStatus,
    EmailAnalysisProviderStatus,
    EmailAnalysisRequest,
    EmailAnalysisResult,
    GeminiEmailAnalysisPayload,
    ResolvedDeadline,
    UnsentReplyDraft,
)
from app.infrastructure.ai.gemini_email_facts import (
    _factual_anchors,
    _log_unsupported_factual_anchors,
)
from app.infrastructure.ai.gemini_email_text import (
    _deadline_is_grounded_in_email,
    _ungrounded_deadline,
)

logger = get_logger("app.infrastructure.ai.gemini_email_analysis_service")


def reject_unsupported_display_facts(
    provider_result: GeminiEmailAnalysisPayload,
    *,
    trusted_anchors: set[tuple[str, str]],
    model: str,
    repair_attempted: bool,
) -> EmailAnalysisResult | None:
    unsupported_summary_anchors = _factual_anchors(provider_result.summary) - trusted_anchors
    if unsupported_summary_anchors:
        _log_unsupported_factual_anchors(
            field="summary",
            anchors=unsupported_summary_anchors,
            model=model,
        )
        return EmailAnalysisResult.review_fallback(
            provider_status=EmailAnalysisProviderStatus.INVALID_RESPONSE,
            reason_code="unsupported_summary_fact",
            model=model,
            repair_attempted=repair_attempted,
        )

    provider_display_fields = (
        (
            "candidate_link_rationale",
            "\n".join(link.rationale for link in provider_result.candidate_links),
        ),
        (
            "risk_rationale",
            "\n".join(risk.rationale for risk in provider_result.risks),
        ),
        (
            "missing_information",
            "\n".join(provider_result.missing_information),
        ),
        (
            "proposal_rationale",
            "\n".join(proposal.rationale for proposal in provider_result.proposals),
        ),
    )
    for field, display_text in provider_display_fields:
        unsupported_display_anchors = _factual_anchors(display_text) - trusted_anchors
        if not unsupported_display_anchors:
            continue
        _log_unsupported_factual_anchors(
            field=field,
            anchors=unsupported_display_anchors,
            model=model,
        )
        return EmailAnalysisResult.review_fallback(
            provider_status=EmailAnalysisProviderStatus.INVALID_RESPONSE,
            reason_code="unsupported_display_fact",
            model=model,
            repair_attempted=repair_attempted,
        )

    return None


def grounded_reply_draft(
    provider_result: GeminiEmailAnalysisPayload,
    *,
    trusted_anchors: set[tuple[str, str]],
    model: str,
) -> tuple[UnsentReplyDraft | None, bool]:
    reply_draft = provider_result.reply_draft
    draft_grounding_failed = False
    if reply_draft is not None:
        unsupported_draft_anchors = (
            _factual_anchors(f"{reply_draft.subject}\n{reply_draft.body}") - trusted_anchors
        )
        if unsupported_draft_anchors:
            _log_unsupported_factual_anchors(
                field="reply_draft",
                anchors=unsupported_draft_anchors,
                model=model,
            )
            reply_draft = None
            draft_grounding_failed = True

    return reply_draft, draft_grounding_failed


def grounded_deadlines(
    provider_result: GeminiEmailAnalysisPayload,
    request: EmailAnalysisRequest,
    *,
    model: str,
    deadline_confidence_threshold: float,
) -> list[ResolvedDeadline]:
    deadlines = []
    for deadline in provider_result.deadlines:
        if not _deadline_is_grounded_in_email(deadline, request):
            logger.warning(
                "email_ai_deadline_not_grounded",
                model=model,
            )
            deadlines.append(_ungrounded_deadline(deadline))
            continue
        resolved = resolve_deadline(
            deadline,
            reference_time=request.received_at,
            timezone_name=request.timezone,
        )
        if (
            resolved.status == DeadlineResolutionStatus.RESOLVED
            and deadline.confidence < deadline_confidence_threshold
        ):
            resolved = resolved.model_copy(
                update={
                    "status": DeadlineResolutionStatus.REVIEW_REQUIRED,
                    "reason_code": "deadline_confidence_below_threshold",
                }
            )
        deadlines.append(resolved)
    return deadlines
