"""Response projection for already-authorized email inbox data."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import overload

from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import EmailConnectionModel, EmailMessageModel
from app.presentation.api.v1.routes.email_ai_inbox_types import InboxView, ProposalAction
from app.presentation.api.v1.schemas.email_ai_schemas import (
    EmailCandidateLinkResponse,
    EmailInboxDeadlineResponse,
    EmailInboxDraftResponse,
    EmailInboxItemResponse,
    EmailInboxProposalResponse,
    EmailIntelligenceResponse,
    EmailLinkedPassengerResponse,
)


def _inbox_item(
    *,
    analysis: EmailAiAnalysisModel,
    message: EmailMessageModel,
    connection: EmailConnectionModel,
    visible_group_id: uuid.UUID | None,
    group_name: str | None,
    deadlines: list[EmailDetectedDeadlineModel],
    proposals: list[EmailActionProposalModel],
    draft: EmailReplyDraftModel | None,
    now: datetime,
    deadline_window_days: int,
) -> EmailInboxItemResponse:
    open_proposals = [
        proposal
        for proposal in proposals
        if proposal.status in {"proposed", "approval_required", "blocked"}
    ]
    deadline_window: list[EmailDetectedDeadlineModel] = []
    for deadline in deadlines:
        due_at = _aware_utc(deadline.due_at)
        if (
            due_at is not None
            and due_at <= now + timedelta(days=deadline_window_days)
            and deadline.status in {"detected", "review_required", "acknowledged"}
        ):
            deadline_window.append(deadline)
    section: InboxView
    if analysis.needs_attention or analysis.status == "review_required" or open_proposals:
        section = "needs_attention"
    elif deadline_window:
        section = "upcoming_deadlines"
    elif draft is not None and draft.status in {"prepared", "edited"}:
        section = "drafts_ready"
    elif analysis.status in {"pending", "processing"}:
        section = "waiting"
    elif analysis.status == "completed":
        section = "completed_automatically"
    else:
        section = "all_activity"
    return EmailInboxItemResponse(
        message_id=message.id,
        analysis_id=analysis.id,
        connection_id=connection.id,
        account_email=connection.email_address,
        provider=connection.provider,
        sender_email=message.sender_address or "Unknown sender",
        sender_name=message.sender_name,
        subject=message.subject or "(No subject)",
        received_at=message.received_at,
        summary=analysis.summary or "Analysis is still being prepared.",
        intent=analysis.intent or "other",
        priority=analysis.priority or "normal",
        confidence=analysis.confidence or 0.0,
        needs_attention=analysis.needs_attention,
        group_id=visible_group_id,
        group_name=group_name,
        status=analysis.status,
        section=section,
        next_deadline=(_deadline_response(deadline_window[0]) if deadline_window else None),
        proposal_count=len(open_proposals),
        draft_status=draft.status if draft is not None else None,
    )


def _intelligence_response(
    analysis: EmailAiAnalysisModel,
    deadlines: list[EmailDetectedDeadlineModel],
    proposals: list[EmailActionProposalModel],
    draft: EmailReplyDraftModel | None,
    *,
    visible_group_id: uuid.UUID | None,
    visible_group_name: str | None,
    visible_passengers: list[tuple[uuid.UUID, str]],
    candidate_links: list[EmailCandidateLinkResponse],
) -> EmailIntelligenceResponse:
    result = analysis.result_json or {}
    return EmailIntelligenceResponse(
        id=analysis.id,
        status=analysis.status,
        intent=analysis.intent,
        priority=analysis.priority,
        summary=analysis.summary,
        confidence=analysis.confidence,
        needs_attention=analysis.needs_attention,
        human_review_confirmed=bool(result.get("human_review_confirmed")),
        linked_group_id=visible_group_id,
        linked_group_name=visible_group_name,
        linked_passenger_ids=[item[0] for item in visible_passengers],
        linked_passengers=[
            EmailLinkedPassengerResponse(id=item[0], name=item[1]) for item in visible_passengers
        ],
        candidate_links=candidate_links,
        risks=_safe_risk_strings(result.get("risks"), 20),
        missing_information=_safe_strings(result.get("missing_information"), 20),
        evidence=_safe_strings(result.get("evidence"), 30),
        model_version=analysis.ai_model,
        schema_version=analysis.prompt_schema_version,
        completed_at=analysis.completed_at,
        updated_at=analysis.updated_at,
        deadlines=[_deadline_response(item) for item in deadlines],
        proposals=[_proposal_response(item) for item in proposals],
        draft=_draft_response(draft) if draft is not None else None,
    )


def _deadline_response(item: EmailDetectedDeadlineModel) -> EmailInboxDeadlineResponse:
    return EmailInboxDeadlineResponse(
        id=item.id,
        deadline_type=item.deadline_type,
        source_phrase=item.source_phrase,
        source_timezone=item.source_timezone,
        due_at=_aware_utc(item.due_at),
        confidence=item.confidence,
        is_ambiguous=item.is_ambiguous,
        status=item.status,
        updated_at=_aware_utc(item.updated_at),
    )


def _proposal_response(item: EmailActionProposalModel) -> EmailInboxProposalResponse:
    allowed_actions: list[ProposalAction]
    if item.status == "blocked":
        allowed_actions = ["reject", "dismiss"]
    elif item.status in {"proposed", "approval_required"}:
        allowed_actions = (
            ["reject", "dismiss"]
            if item.risk_level in {"high", "critical"}
            else ["approve", "reject", "dismiss"]
        )
    else:
        allowed_actions = []
    return EmailInboxProposalResponse(
        id=item.id,
        action_type=item.action_type,
        risk_level=item.risk_level,
        status=item.status,
        explanation=item.explanation,
        confidence=item.confidence,
        requires_approval=item.requires_approval,
        allowed_actions=allowed_actions,
        revision=item.revision,
    )


def _draft_response(item: EmailReplyDraftModel) -> EmailInboxDraftResponse:
    return EmailInboxDraftResponse(
        id=item.id,
        recipients=item.recipients_json,
        subject=item.subject,
        body_text=item.body_text,
        status=item.status,
        revision=item.revision,
        sending_available=False,
        updated_at=item.updated_at,
    )


def _safe_strings(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:500] for item in value if isinstance(item, str)][:limit]


@overload
def _aware_utc(value: datetime) -> datetime: ...


@overload
def _aware_utc(value: None) -> None: ...


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _safe_risk_strings(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    risks: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        level = item.get("level")
        rationale = item.get("rationale")
        if not all(isinstance(part, str) for part in (code, level, rationale)):
            continue
        label = str(code).replace("_", " ").strip().title()
        severity = str(level).strip().upper()
        explanation = str(rationale).strip()
        if not label or not severity or not explanation:
            continue
        risks.append(f"{severity} — {label}: {explanation}"[:500])
        if len(risks) >= limit:
            break
    return risks


def _result_group_id(analysis: EmailAiAnalysisModel) -> uuid.UUID | None:
    result_json = analysis.result_json or {}
    value = result_json.get("linked_group_id")
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _same_instant(left: datetime, right: datetime) -> bool:
    left_utc = _aware_utc(left)
    right_utc = _aware_utc(right)
    return left_utc is not None and right_utc is not None and left_utc == right_utc
