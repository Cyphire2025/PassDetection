"""Feedback for the owner-scoped email inbox."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailAiFeedbackModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.presentation.api.v1.routes import email_ai_inbox_activity as _activity
from app.presentation.api.v1.routes import email_ai_inbox_corrections as _corrections
from app.presentation.api.v1.routes import email_ai_inbox_scope as _scope
from app.presentation.api.v1.routes.email_ai_inbox_responses import _same_instant
from app.presentation.api.v1.routes.email_ai_inbox_types import AttentionUpdater
from app.presentation.api.v1.schemas.email_ai_schemas import (
    EmailAiFeedbackRequest,
    EmailAiFeedbackResponse,
)

_owner_predicates = _scope._owner_predicates
_apply_typed_correction = _corrections._apply_typed_correction
_invalidate_generated_work_after_correction = (
    _corrections._invalidate_generated_work_after_correction
)
_analysis_feedback_snapshot = _activity._analysis_feedback_snapshot
_correction_activity_display_values = _activity._correction_activity_display_values
_decision_activity_event = _activity._decision_activity_event


async def create_email_ai_feedback(
    analysis_id: uuid.UUID,
    payload: EmailAiFeedbackRequest,
    current_user: User,
    session: AsyncSession,
    _refresh_analysis_attention: AttentionUpdater,
) -> EmailAiFeedbackResponse:
    result = await session.execute(
        select(EmailAiAnalysisModel)
        .where(
            EmailAiAnalysisModel.id == analysis_id,
            *_owner_predicates(EmailAiAnalysisModel, current_user),
        )
        .with_for_update()
    )
    analysis = result.scalar_one_or_none()
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email intelligence was not found.",
        )
    if analysis.status != payload.expected_status or not _same_instant(
        analysis.updated_at,
        payload.expected_updated_at,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This AI brief changed. Refresh it before responding.",
        )
    if analysis.status not in {"completed", "review_required", "ignored"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Feedback is available after this AI brief finishes.",
        )
    if analysis.status == "ignored" and payload.feedback_type != "correction":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An ignored brief can be corrected but not confirmed or dismissed again.",
        )
    if (
        payload.feedback_type == "confirmation"
        and (analysis.result_json or {}).get("human_review_confirmed") is True
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This AI brief review is already confirmed.",
        )
    now = datetime.now(tz=UTC)
    if payload.feedback_type == "correction":
        original_value, corrected_value = await _apply_typed_correction(
            session,
            analysis=analysis,
            payload=payload,
            current_user=current_user,
            now=now,
        )
        generated_work_invalidated = await _invalidate_generated_work_after_correction(
            session,
            analysis=analysis,
            field_name=payload.field_name,
            current_user=current_user,
            now=now,
        )
        corrected_value["generated_work_invalidated"] = generated_work_invalidated
    else:
        original_value = _analysis_feedback_snapshot(analysis)
        corrected_value = {}
    feedback = EmailAiFeedbackModel(
        agency_id=analysis.agency_id,
        owner_user_id=analysis.owner_user_id,
        connection_id=analysis.connection_id,
        message_id=analysis.message_id,
        analysis_id=analysis.id,
        feedback_type=payload.feedback_type,
        field_name=payload.field_name,
        original_value=original_value,
        corrected_value=corrected_value,
        note=payload.note,
        created_by_user_id=current_user.id,
    )
    session.add(feedback)
    await session.flush()
    if payload.feedback_type == "correction":
        corrected_result = dict(analysis.result_json or {})
        corrected_result.pop("human_review_confirmed", None)
        corrected_result.pop("human_review_confirmed_at", None)
        corrected_result.pop("human_correction_pending", None)
        corrected_fields = corrected_result.get("human_corrected_fields")
        if not isinstance(corrected_fields, list):
            corrected_fields = []
        if payload.field_name not in corrected_fields:
            corrected_fields.append(payload.field_name)
        corrected_result["human_corrected_fields"] = corrected_fields[-20:]
        corrected_result["last_corrected_field"] = payload.field_name
        corrected_result["last_correction_at"] = now.isoformat()
        corrected_result["last_feedback_id"] = str(feedback.id)
        analysis.result_json = corrected_result
        analysis.status = "review_required"
        analysis.needs_attention = True
        analysis.updated_at = now
        before_display, after_display = _correction_activity_display_values(
            field_name=payload.field_name,
            original_value=feedback.original_value,
            corrected_value=feedback.corrected_value,
        )
        session.add(
            _decision_activity_event(
                analysis=analysis,
                actor_user_id=current_user.id,
                event_key=f"email-ai-analysis:{analysis.id}:corrected:{feedback.id}",
                event_type="ai_analysis_corrected",
                summary_code="email_ai_analysis_corrected",
                details={
                    "analysis_id": str(analysis.id),
                    "feedback_id": str(feedback.id),
                    "field_name": payload.field_name,
                    "correction_applied": True,
                    "generated_work_invalidated": (generated_work_invalidated),
                    "before_value": before_display,
                    "after_value": after_display,
                    "external_action_performed": False,
                },
                changed_entity_type="email_ai_analysis",
                changed_entity_id=analysis.id,
                confidence=analysis.confidence,
            )
        )
        await session.flush()
    elif payload.feedback_type == "confirmation":
        confirmed_result = dict(analysis.result_json or {})
        confirmed_result["human_review_confirmed"] = True
        confirmed_result["human_review_confirmed_at"] = now.isoformat()
        analysis.result_json = confirmed_result
        await _refresh_analysis_attention(session, analysis)
        session.add(
            _decision_activity_event(
                analysis=analysis,
                actor_user_id=current_user.id,
                event_key=f"email-ai-analysis:{analysis.id}:confirmed:{feedback.id}",
                event_type="ai_analysis_confirmed",
                summary_code="email_ai_analysis_confirmed",
                details={
                    "analysis_id": str(analysis.id),
                    "feedback_id": str(feedback.id),
                    "external_action_performed": False,
                },
                changed_entity_type="email_ai_analysis",
                changed_entity_id=analysis.id,
                confidence=analysis.confidence,
            )
        )
        await session.flush()
    elif payload.feedback_type == "dismissal":
        dismissed_result = dict(analysis.result_json or {})
        dismissed_result["human_dismissed"] = True
        dismissed_result["human_dismissed_at"] = now.isoformat()
        analysis.result_json = dismissed_result
        analysis.status = "ignored"
        analysis.needs_attention = False
        analysis.completed_at = analysis.completed_at or now
        analysis.updated_at = now
        await session.execute(
            update(EmailActionProposalModel)
            .where(
                EmailActionProposalModel.analysis_id == analysis.id,
                *_owner_predicates(EmailActionProposalModel, current_user),
                EmailActionProposalModel.status.in_({"proposed", "approval_required", "blocked"}),
            )
            .values(
                status="dismissed",
                decision_by_user_id=current_user.id,
                decision_at=now,
                decision_note="Dismissed with the full AI brief.",
                revision=EmailActionProposalModel.revision + 1,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        await session.execute(
            update(EmailDetectedDeadlineModel)
            .where(
                EmailDetectedDeadlineModel.analysis_id == analysis.id,
                *_owner_predicates(EmailDetectedDeadlineModel, current_user),
                EmailDetectedDeadlineModel.status.in_(
                    {"detected", "review_required", "acknowledged"}
                ),
            )
            .values(status="dismissed", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        await session.execute(
            update(EmailReplyDraftModel)
            .where(
                EmailReplyDraftModel.analysis_id == analysis.id,
                *_owner_predicates(EmailReplyDraftModel, current_user),
                EmailReplyDraftModel.status.in_({"prepared", "edited", "approved"}),
            )
            .values(
                status="dismissed",
                revision=EmailReplyDraftModel.revision + 1,
                edited_by_user_id=current_user.id,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        session.add(
            _decision_activity_event(
                analysis=analysis,
                actor_user_id=current_user.id,
                event_key=f"email-ai-analysis:{analysis.id}:dismissed:{feedback.id}",
                event_type="ai_analysis_dismissed",
                summary_code="email_ai_analysis_dismissed",
                details={
                    "analysis_id": str(analysis.id),
                    "feedback_id": str(feedback.id),
                    "external_action_performed": False,
                },
                changed_entity_type="email_ai_analysis",
                changed_entity_id=analysis.id,
                confidence=analysis.confidence,
            )
        )
        await session.flush()
    return EmailAiFeedbackResponse(
        feedback_id=feedback.id,
        analysis_id=analysis.id,
        created_at=feedback.created_at,
        analysis_status=analysis.status,
        analysis_updated_at=analysis.updated_at,
    )
