"""Validate factual grounding, deadlines and non-executable action suggestions."""

from __future__ import annotations

from app.application.use_cases.email_integrations.action_policy import EmailActionPolicy
from app.domain.value_objects.email_ai_analysis import (
    ActionDisposition,
    ActionPolicyDecision,
    CandidateEntityType,
    DeadlineResolutionStatus,
    EmailAnalysisProviderStatus,
    EmailAnalysisRequest,
    EmailAnalysisResult,
    EmailIntent,
    EmailPriority,
    EmailRelevance,
    GeminiEmailAnalysisPayload,
    ResolvedDeadline,
    RiskLevel,
)
from app.infrastructure.ai.gemini_email_facts import (
    _factual_anchors,
)
from app.infrastructure.ai.gemini_email_grounding import (
    grounded_deadlines,
    grounded_reply_draft,
    reject_unsupported_display_facts,
)
from app.infrastructure.ai.gemini_email_text import (
    _trusted_fact_corpus,
)


def build_email_analysis_result(
    provider_result: GeminiEmailAnalysisPayload,
    request: EmailAnalysisRequest,
    *,
    repair_attempted: bool,
    model: str,
    review_confidence_threshold: float,
    deadline_confidence_threshold: float,
    action_policy: EmailActionPolicy,
) -> EmailAnalysisResult:
    trusted_anchors = _factual_anchors(_trusted_fact_corpus(request))
    rejected = reject_unsupported_display_facts(
        provider_result,
        trusted_anchors=trusted_anchors,
        model=model,
        repair_attempted=repair_attempted,
    )
    if rejected is not None:
        return rejected
    reply_draft, draft_grounding_failed = grounded_reply_draft(
        provider_result, trusted_anchors=trusted_anchors, model=model
    )
    deadlines = grounded_deadlines(
        provider_result,
        request,
        model=model,
        deadline_confidence_threshold=deadline_confidence_threshold,
    )
    resolved_expressions = {
        deadline.expression
        for deadline in deadlines
        if deadline.status == DeadlineResolutionStatus.RESOLVED
    }
    visible_aliases = {candidate.alias for candidate in request.visible_candidates}
    decisions = [
        action_policy.evaluate(
            proposal,
            visible_aliases=visible_aliases,
            resolved_deadline_expressions=resolved_expressions,
            has_reply_draft=reply_draft is not None,
            allow_first_slice_proposals=(provider_result.relevance != EmailRelevance.UNRELATED),
            link_confidence_threshold=review_confidence_threshold,
        )
        for proposal in provider_result.proposals
    ]
    needs_review = _requires_review(
        provider_result,
        request,
        review_confidence_threshold=review_confidence_threshold,
        deadlines=deadlines,
        decisions=decisions,
        draft_grounding_failed=draft_grounding_failed,
    )
    return EmailAnalysisResult(
        provider_status=EmailAnalysisProviderStatus.ANALYZED,
        reason_code=("unsupported_draft_fact" if draft_grounding_failed else None),
        model=model,
        repair_attempted=repair_attempted,
        relevance=provider_result.relevance,
        intent=provider_result.intent,
        priority=provider_result.priority,
        confidence=provider_result.confidence,
        summary=provider_result.summary,
        candidate_links=provider_result.candidate_links,
        deadlines=deadlines,
        risks=provider_result.risks,
        missing_information=provider_result.missing_information,
        proposals=provider_result.proposals,
        action_decisions=decisions,
        reply_draft=reply_draft,
        needs_review=needs_review,
    )


def _has_ambiguous_candidate_links(
    result: GeminiEmailAnalysisPayload,
    request: EmailAnalysisRequest,
) -> bool:
    candidates = {candidate.alias: candidate for candidate in request.visible_candidates}
    linked_candidates = [
        candidates[link.alias] for link in result.candidate_links if link.alias in candidates
    ]
    if (
        sum(candidate.entity_type == CandidateEntityType.GROUP for candidate in linked_candidates)
        > 1
    ):
        return True

    passenger_names: list[str] = []
    for candidate in linked_candidates:
        if candidate.entity_type != CandidateEntityType.PASSENGER:
            continue
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
    return len(passenger_names) != len(set(passenger_names))


def _requires_review(
    provider_result: GeminiEmailAnalysisPayload,
    request: EmailAnalysisRequest,
    *,
    review_confidence_threshold: float,
    deadlines: list[ResolvedDeadline],
    decisions: list[ActionPolicyDecision],
    draft_grounding_failed: bool,
) -> bool:
    return (
        provider_result.relevance == EmailRelevance.POSSIBLY_RELEVANT
        or provider_result.confidence < review_confidence_threshold
        or provider_result.priority == EmailPriority.URGENT
        or provider_result.intent in {EmailIntent.CANCELLATION, EmailIntent.PAYMENT}
        or any(
            link.confidence < review_confidence_threshold
            for link in provider_result.candidate_links
        )
        or _has_ambiguous_candidate_links(provider_result, request)
        or any(
            deadline.status == DeadlineResolutionStatus.REVIEW_REQUIRED for deadline in deadlines
        )
        or any(decision.disposition == ActionDisposition.BLOCKED for decision in decisions)
        or any(risk.level in {RiskLevel.HIGH, RiskLevel.CRITICAL} for risk in provider_result.risks)
        or draft_grounding_failed
    )
