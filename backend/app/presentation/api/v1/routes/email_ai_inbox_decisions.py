"""Decisions for the owner-scoped email inbox."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailAiFeedbackModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import EmailActivityEventModel
from app.presentation.api.v1.routes import email_ai_inbox_activity as _activity
from app.presentation.api.v1.routes import email_ai_inbox_responses as _responses
from app.presentation.api.v1.routes import email_ai_inbox_scope as _scope
from app.presentation.api.v1.routes.email_ai_inbox_responses import _same_instant
from app.presentation.api.v1.routes.email_ai_inbox_types import AttentionUpdater
from app.presentation.api.v1.schemas.email_ai_schemas import (
    DecideEmailDeadlineRequest,
    DecideEmailDraftRequest,
    DecideEmailProposalRequest,
    EmailInboxDeadlineResponse,
    EmailInboxDraftResponse,
    EmailProposalDecisionResponse,
    UpdateEmailReplyDraftRequest,
)

_owner_predicates = _scope._owner_predicates
_deadline_response = _responses._deadline_response
_draft_response = _responses._draft_response
_decision_activity_event = _activity._decision_activity_event


async def decide_email_proposal(
    proposal_id: uuid.UUID,
    payload: DecideEmailProposalRequest,
    current_user: User,
    session: AsyncSession,
    _refresh_analysis_attention: AttentionUpdater,
) -> EmailProposalDecisionResponse:
    result = await session.execute(
        select(EmailActionProposalModel, EmailAiAnalysisModel)
        .join(
            EmailAiAnalysisModel,
            and_(
                EmailAiAnalysisModel.id == EmailActionProposalModel.analysis_id,
                EmailAiAnalysisModel.agency_id == EmailActionProposalModel.agency_id,
                EmailAiAnalysisModel.owner_user_id == EmailActionProposalModel.owner_user_id,
            ),
        )
        .where(
            EmailActionProposalModel.id == proposal_id,
            *_owner_predicates(EmailActionProposalModel, current_user),
        )
        .with_for_update()
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email action proposal was not found.",
        )
    proposal, analysis = row
    if proposal.revision != payload.expected_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This proposal changed. Refresh before deciding.",
        )
    if proposal.status not in {"proposed", "approval_required", "blocked"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This proposal is no longer awaiting a decision.",
        )
    if payload.action == "approve" and (
        proposal.status == "blocked" or proposal.risk_level in {"high", "critical"}
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This high-risk action cannot be executed from the AI inbox.",
        )

    proposal.status = {
        "approve": "approved",
        "reject": "rejected",
        "dismiss": "dismissed",
    }[payload.action]
    proposal.decision_by_user_id = current_user.id
    proposal.decision_at = datetime.now(tz=UTC)
    proposal.decision_note = payload.note
    proposal.revision += 1
    await session.flush()
    await _refresh_analysis_attention(session, analysis)
    session.add(
        EmailActivityEventModel(
            agency_id=proposal.agency_id,
            owner_user_id=proposal.owner_user_id,
            connection_id=proposal.connection_id,
            message_id=proposal.message_id,
            event_key=(f"email-ai-proposal:{proposal.id}:decision:{proposal.revision}"),
            event_type="ai_action_proposal_decided",
            stage="info",
            actor_type="user",
            actor_user_id=current_user.id,
            summary_code=f"email_ai_proposal_{proposal.status}",
            details={
                "proposal_id": str(proposal.id),
                "action_type": proposal.action_type,
                "risk_level": proposal.risk_level,
                "decision": payload.action,
                "revision": proposal.revision,
            },
            ai_used=True,
            ai_provider=analysis.ai_provider,
            ai_model=analysis.ai_model,
            confidence=proposal.confidence,
            changed_entity_type="email_action_proposal",
            changed_entity_id=proposal.id,
        )
    )
    return EmailProposalDecisionResponse(
        proposal_id=proposal.id,
        status=proposal.status,
        revision=proposal.revision,
        message=("Decision saved. No external message or high-risk change was performed."),
    )


async def decide_email_deadline(
    deadline_id: uuid.UUID,
    payload: DecideEmailDeadlineRequest,
    current_user: User,
    session: AsyncSession,
    _refresh_analysis_attention: AttentionUpdater,
) -> EmailInboxDeadlineResponse:
    result = await session.execute(
        select(EmailDetectedDeadlineModel, EmailAiAnalysisModel)
        .join(
            EmailAiAnalysisModel,
            and_(
                EmailAiAnalysisModel.id == EmailDetectedDeadlineModel.analysis_id,
                EmailAiAnalysisModel.agency_id == EmailDetectedDeadlineModel.agency_id,
                EmailAiAnalysisModel.owner_user_id == EmailDetectedDeadlineModel.owner_user_id,
            ),
        )
        .where(
            EmailDetectedDeadlineModel.id == deadline_id,
            *_owner_predicates(EmailDetectedDeadlineModel, current_user),
        )
        .with_for_update()
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email deadline was not found.",
        )
    deadline, analysis = row
    if deadline.status != payload.expected_status or not _same_instant(
        deadline.updated_at,
        payload.expected_updated_at,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This deadline changed. Refresh before deciding.",
        )
    if payload.action == "acknowledge" and deadline.status not in {
        "detected",
        "review_required",
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This deadline is already acknowledged.",
        )

    deadline.status = {
        "acknowledge": "acknowledged",
        "complete": "completed",
        "dismiss": "dismissed",
    }[payload.action]
    deadline.updated_at = datetime.now(tz=UTC)
    await session.flush()
    await _refresh_analysis_attention(session, analysis)
    session.add(
        _decision_activity_event(
            analysis=analysis,
            actor_user_id=current_user.id,
            event_key=f"email-ai-deadline:{deadline.id}:{deadline.status}",
            event_type="ai_deadline_decided",
            summary_code=f"email_ai_deadline_{deadline.status}",
            details={
                "deadline_id": str(deadline.id),
                "decision": payload.action,
                "status": deadline.status,
            },
            changed_entity_type="email_detected_deadline",
            changed_entity_id=deadline.id,
            confidence=deadline.confidence,
        )
    )
    return _deadline_response(deadline)


async def decide_email_reply_draft(
    draft_id: uuid.UUID,
    payload: DecideEmailDraftRequest,
    current_user: User,
    session: AsyncSession,
    _refresh_analysis_attention: AttentionUpdater,
) -> EmailInboxDraftResponse:
    result = await session.execute(
        select(EmailReplyDraftModel, EmailAiAnalysisModel)
        .join(
            EmailAiAnalysisModel,
            and_(
                EmailAiAnalysisModel.id == EmailReplyDraftModel.analysis_id,
                EmailAiAnalysisModel.agency_id == EmailReplyDraftModel.agency_id,
                EmailAiAnalysisModel.owner_user_id == EmailReplyDraftModel.owner_user_id,
            ),
        )
        .where(
            EmailReplyDraftModel.id == draft_id,
            *_owner_predicates(EmailReplyDraftModel, current_user),
        )
        .with_for_update()
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prepared reply draft was not found.",
        )
    draft, analysis = row
    if draft.revision != payload.expected_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This draft changed. Refresh before deciding.",
        )
    allowed_statuses = (
        {"prepared", "edited"}
        if payload.action == "approve"
        else {"prepared", "edited", "approved"}
    )
    if draft.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This draft is no longer awaiting that decision.",
        )

    draft.status = "approved" if payload.action == "approve" else "dismissed"
    draft.revision += 1
    draft.edited_by_user_id = current_user.id
    draft.updated_at = datetime.now(tz=UTC)
    await session.flush()
    await _refresh_analysis_attention(session, analysis)
    session.add(
        _decision_activity_event(
            analysis=analysis,
            actor_user_id=current_user.id,
            event_key=f"email-ai-draft:{draft.id}:{draft.revision}",
            event_type="ai_reply_draft_decided",
            summary_code=f"email_ai_draft_{draft.status}",
            details={
                "draft_id": str(draft.id),
                "decision": payload.action,
                "revision": draft.revision,
                "sending_performed": False,
            },
            changed_entity_type="email_reply_draft",
            changed_entity_id=draft.id,
            confidence=analysis.confidence,
        )
    )
    return _draft_response(draft)


async def update_email_reply_draft(
    draft_id: uuid.UUID,
    payload: UpdateEmailReplyDraftRequest,
    current_user: User,
    session: AsyncSession,
    _refresh_analysis_attention: AttentionUpdater,
) -> EmailInboxDraftResponse:
    result = await session.execute(
        select(EmailReplyDraftModel, EmailAiAnalysisModel)
        .join(
            EmailAiAnalysisModel,
            and_(
                EmailAiAnalysisModel.id == EmailReplyDraftModel.analysis_id,
                EmailAiAnalysisModel.agency_id == EmailReplyDraftModel.agency_id,
                EmailAiAnalysisModel.owner_user_id == EmailReplyDraftModel.owner_user_id,
            ),
        )
        .where(
            EmailReplyDraftModel.id == draft_id,
            *_owner_predicates(EmailReplyDraftModel, current_user),
        )
        .with_for_update()
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prepared reply draft was not found.",
        )
    draft, analysis = row
    if draft.revision != payload.expected_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This draft changed. Refresh before editing.",
        )
    if draft.status not in {"prepared", "edited"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This draft is no longer editable.",
        )
    original_draft = {
        "draft_id": str(draft.id),
        "subject": draft.subject,
        "body_text": draft.body_text,
        "status": draft.status,
        "revision": draft.revision,
    }
    draft.subject = payload.subject.strip()
    draft.body_text = payload.body_text.strip()
    draft.status = "edited"
    draft.revision += 1
    draft.edited_by_user_id = current_user.id
    draft.updated_at = datetime.now(tz=UTC)
    feedback = EmailAiFeedbackModel(
        agency_id=analysis.agency_id,
        owner_user_id=analysis.owner_user_id,
        connection_id=analysis.connection_id,
        message_id=analysis.message_id,
        analysis_id=analysis.id,
        feedback_type="correction",
        field_name="draft",
        original_value=original_draft,
        corrected_value={
            "draft_id": str(draft.id),
            "subject": draft.subject,
            "body_text": draft.body_text,
            "status": draft.status,
            "revision": draft.revision,
        },
        note="Prepared reply corrected in the draft editor.",
        created_by_user_id=current_user.id,
    )
    session.add(feedback)
    await session.flush()
    session.add(
        _decision_activity_event(
            analysis=analysis,
            actor_user_id=current_user.id,
            event_key=f"email-ai-draft:{draft.id}:edited:{draft.revision}",
            event_type="ai_reply_draft_edited",
            summary_code="email_ai_draft_edited",
            details={
                "draft_id": str(draft.id),
                "revision": draft.revision,
                "feedback_id": str(feedback.id),
                "correction_applied": True,
                "sending_performed": False,
            },
            changed_entity_type="email_reply_draft",
            changed_entity_id=draft.id,
            confidence=analysis.confidence,
        )
    )
    return _draft_response(draft)
