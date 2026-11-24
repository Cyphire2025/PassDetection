"""Stage exact deduplicated deadlines, approval-only proposals and unsent drafts."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.domain.value_objects.email_ai_analysis import (
    ActionDisposition,
    DeadlineResolutionStatus,
    EmailAnalysisResult,
)
from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import EmailMessageModel
from app.infrastructure.email.ai_context import EmailAiContext
from app.infrastructure.email.ai_values import _safe_reply_address


def stage_deadlines(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    result: EmailAnalysisResult,
    settings: Settings,
    operational_result: bool,
) -> list[EmailDetectedDeadlineModel]:
    persisted_deadlines: list[EmailDetectedDeadlineModel] = []
    deadline_fingerprints: set[str] = set()
    for deadline in result.deadlines if operational_result else []:
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "source_text": deadline.source_text,
                    "expression": deadline.expression,
                    "due_at": (
                        deadline.due_at.isoformat() if deadline.due_at is not None else None
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
            is_ambiguous=(deadline.status == DeadlineResolutionStatus.REVIEW_REQUIRED),
            status=(
                "review_required"
                if deadline.status == DeadlineResolutionStatus.REVIEW_REQUIRED
                else "detected"
            ),
            resolution_evidence={"reason_code": deadline.reason_code},
        )
        session.add(deadline_row)
        persisted_deadlines.append(deadline_row)

    return persisted_deadlines


def stage_proposals(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    result: EmailAnalysisResult,
    context: EmailAiContext,
    operational_result: bool,
) -> int:
    decisions_by_index = list(result.action_decisions)
    proposal_idempotency_keys: set[str] = set()
    for index, proposal in enumerate(result.proposals if operational_result else []):
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
                requires_approval=(decision.disposition == ActionDisposition.PROPOSAL_ONLY),
                idempotency_key=idempotency_key,
            )
        )

    return len(proposal_idempotency_keys)


def stage_reply_draft(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    message: EmailMessageModel,
    result: EmailAnalysisResult,
    operational_result: bool,
) -> EmailReplyDraftModel | None:
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

    return draft
