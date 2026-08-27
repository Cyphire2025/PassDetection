"""Owner-only API for the AI Travel Operations Inbox."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, TypeAlias, cast, overload

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, exists, false, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.email_integrations.analysis_contract import (
    EMAIL_AI_SCHEMA_VERSION,
)
from app.application.use_cases.email_integrations.rollout_policy import (
    email_ai_policy_allows,
)
from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailAiFeedbackModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailConnectionModel,
    EmailMessageModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    NotificationModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.schemas.email_ai_schemas import (
    DecideEmailDeadlineRequest,
    DecideEmailDraftRequest,
    DecideEmailProposalRequest,
    EmailAiFeedbackRequest,
    EmailAiFeedbackResponse,
    EmailAiRetryResponse,
    EmailCandidateLinkResponse,
    EmailInboxCountsResponse,
    EmailInboxDeadlineResponse,
    EmailInboxDraftResponse,
    EmailInboxItemResponse,
    EmailInboxProposalResponse,
    EmailInboxResponse,
    EmailIntelligenceResponse,
    EmailLinkedPassengerResponse,
    EmailProposalDecisionResponse,
    UpdateEmailReplyDraftRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()

EMAIL_AI_INBOX_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
]
_current_email_ai_user = require_role(EMAIL_AI_INBOX_ROLES)

InboxView = Literal[
    "needs_attention",
    "upcoming_deadlines",
    "drafts_ready",
    "waiting",
    "completed_automatically",
    "all_activity",
]
CandidateEntityType = Literal["group", "passenger"]
ResolvedCandidateLink: TypeAlias = tuple[
    CandidateEntityType,
    uuid.UUID,
    float,
    str,
]
ProposalAction = Literal["approve", "reject", "dismiss"]
_OwnerScopedModel: TypeAlias = (
    type[EmailAiAnalysisModel]
    | type[EmailActionProposalModel]
    | type[EmailDetectedDeadlineModel]
    | type[EmailReplyDraftModel]
)


def _owner_predicates(
    model: _OwnerScopedModel,
    user: User,
) -> list[ColumnElement[bool]]:
    predicates: list[ColumnElement[bool]] = [model.owner_user_id == user.id]
    if user.role != UserRole.SUPER_ADMIN:
        if user.agency_id is None:
            predicates.append(false())
            return predicates
        predicates.append(model.agency_id == user.agency_id)
    return predicates


def _section_predicates(
    now: datetime,
    *,
    deadline_window_days: int,
) -> dict[InboxView, ColumnElement[bool]]:
    approval_exists = exists(
        select(1).where(
            EmailActionProposalModel.analysis_id == EmailAiAnalysisModel.id,
            EmailActionProposalModel.owner_user_id == EmailAiAnalysisModel.owner_user_id,
            EmailActionProposalModel.status.in_({"proposed", "approval_required", "blocked"}),
        )
    )
    active_deadline_exists = exists(
        select(1).where(
            EmailDetectedDeadlineModel.analysis_id == EmailAiAnalysisModel.id,
            EmailDetectedDeadlineModel.owner_user_id == EmailAiAnalysisModel.owner_user_id,
            EmailDetectedDeadlineModel.status.in_({"detected", "review_required", "acknowledged"}),
            EmailDetectedDeadlineModel.due_at.is_not(None),
        )
    )
    deadline_window_exists = exists(
        select(1).where(
            EmailDetectedDeadlineModel.analysis_id == EmailAiAnalysisModel.id,
            EmailDetectedDeadlineModel.owner_user_id == EmailAiAnalysisModel.owner_user_id,
            EmailDetectedDeadlineModel.status.in_({"detected", "review_required", "acknowledged"}),
            EmailDetectedDeadlineModel.due_at.is_not(None),
            EmailDetectedDeadlineModel.due_at <= now + timedelta(days=deadline_window_days),
        )
    )
    draft_exists = exists(
        select(1).where(
            EmailReplyDraftModel.analysis_id == EmailAiAnalysisModel.id,
            EmailReplyDraftModel.owner_user_id == EmailAiAnalysisModel.owner_user_id,
            EmailReplyDraftModel.status.in_({"prepared", "edited"}),
        )
    )
    needs_attention = or_(
        EmailAiAnalysisModel.needs_attention.is_(True),
        EmailAiAnalysisModel.status == "review_required",
        approval_exists,
    )
    waiting = EmailAiAnalysisModel.status.in_({"pending", "processing"})
    completed = and_(
        EmailAiAnalysisModel.status == "completed",
        EmailAiAnalysisModel.needs_attention.is_(False),
        ~approval_exists,
        ~draft_exists,
        ~active_deadline_exists,
    )
    sections: dict[InboxView, ColumnElement[bool]] = {
        "needs_attention": needs_attention,
        "upcoming_deadlines": deadline_window_exists,
        "drafts_ready": draft_exists,
        "waiting": waiting,
        "completed_automatically": completed,
        "all_activity": EmailAiAnalysisModel.id.is_not(None),
    }
    return sections


def _latest_analyses(user: User) -> Subquery:
    return (
        select(
            EmailAiAnalysisModel.message_id.label("message_id"),
            func.max(EmailAiAnalysisModel.created_at).label("latest_created_at"),
        )
        .where(*_owner_predicates(EmailAiAnalysisModel, user))
        .group_by(EmailAiAnalysisModel.message_id)
        .subquery()
    )


@router.get("/inbox", response_model=EmailInboxResponse)
async def email_operations_inbox(
    view: InboxView = "needs_attention",
    cursor: str | None = Query(default=None, max_length=1000),
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(_current_email_ai_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailInboxResponse:
    now = datetime.now(tz=UTC)
    deadline_window_days = get_settings().email_ai_deadline_notification_window_days
    latest = _latest_analyses(current_user)
    sections = _section_predicates(
        now,
        deadline_window_days=deadline_window_days,
    )
    statement = (
        select(
            EmailAiAnalysisModel,
            EmailMessageModel,
            EmailConnectionModel,
        )
        .join(
            latest,
            and_(
                latest.c.message_id == EmailAiAnalysisModel.message_id,
                latest.c.latest_created_at == EmailAiAnalysisModel.created_at,
            ),
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
        .where(
            *_owner_predicates(EmailAiAnalysisModel, current_user),
            sections[view],
        )
    )
    if cursor is not None:
        cursor_rank, cursor_time, cursor_id = _decode_cursor(cursor)
        priority_order = _priority_order()
        statement = statement.where(
            or_(
                priority_order > cursor_rank,
                and_(
                    priority_order == cursor_rank,
                    or_(
                        EmailAiAnalysisModel.updated_at < cursor_time,
                        and_(
                            EmailAiAnalysisModel.updated_at == cursor_time,
                            EmailAiAnalysisModel.id < cursor_id,
                        ),
                    ),
                ),
            )
        )
    priority_order = _priority_order()
    result = await session.execute(
        statement.order_by(
            priority_order,
            EmailAiAnalysisModel.updated_at.desc(),
            EmailAiAnalysisModel.id.desc(),
        ).limit(limit + 1)
    )
    rows = list(result.all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    analysis_ids = [row[0].id for row in rows]
    deadlines, proposals, drafts = await _load_children(
        session,
        analysis_ids,
        current_user,
    )
    visible_groups = await _load_visible_linked_groups(
        session,
        analyses_and_messages=[(row[0], row[1]) for row in rows],
        current_user=current_user,
    )

    items = [
        _inbox_item(
            analysis=row[0],
            message=row[1],
            connection=row[2],
            visible_group_id=(
                visible_groups[row[0].id].id if row[0].id in visible_groups else None
            ),
            group_name=(visible_groups[row[0].id].name if row[0].id in visible_groups else None),
            deadlines=deadlines.get(row[0].id, []),
            proposals=proposals.get(row[0].id, []),
            draft=drafts.get(row[0].id),
            now=now,
            deadline_window_days=deadline_window_days,
        )
        for row in rows
    ]
    counts = await _inbox_counts(session, current_user, latest, sections)
    next_cursor = (
        _encode_cursor(
            rows[-1][0].priority,
            rows[-1][0].updated_at,
            rows[-1][0].id,
        )
        if has_more and rows
        else None
    )
    return EmailInboxResponse(items=items, counts=counts, next_cursor=next_cursor)


@router.get(
    "/messages/{message_id}/intelligence",
    response_model=EmailIntelligenceResponse,
)
async def email_message_intelligence(
    message_id: uuid.UUID,
    current_user: User = Depends(_current_email_ai_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailIntelligenceResponse:
    result = await session.execute(
        select(EmailAiAnalysisModel, EmailMessageModel)
        .join(
            EmailMessageModel,
            and_(
                EmailMessageModel.id == EmailAiAnalysisModel.message_id,
                EmailMessageModel.connection_id == EmailAiAnalysisModel.connection_id,
                EmailMessageModel.agency_id == EmailAiAnalysisModel.agency_id,
                EmailMessageModel.owner_user_id == EmailAiAnalysisModel.owner_user_id,
            ),
        )
        .where(
            EmailAiAnalysisModel.message_id == message_id,
            *_owner_predicates(EmailAiAnalysisModel, current_user),
        )
        .order_by(EmailAiAnalysisModel.created_at.desc())
        .limit(1)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email intelligence was not found.",
        )
    analysis, message = row
    deadlines, proposals, drafts = await _load_children(
        session,
        [analysis.id],
        current_user,
    )
    visible_groups = await _load_visible_linked_groups(
        session,
        analyses_and_messages=[(analysis, message)],
        current_user=current_user,
    )
    visible_group = visible_groups.get(analysis.id)
    visible_passengers = await _load_visible_linked_passengers(
        session,
        analysis=analysis,
        current_user=current_user,
    )
    candidate_links = await _load_visible_candidate_links(
        session,
        analysis=analysis,
        current_user=current_user,
        canonical_passenger_ids={item[0] for item in visible_passengers},
    )
    return _intelligence_response(
        analysis,
        deadlines.get(analysis.id, []),
        proposals.get(analysis.id, []),
        drafts.get(analysis.id),
        visible_group_id=visible_group.id if visible_group is not None else None,
        visible_group_name=visible_group.name if visible_group is not None else None,
        visible_passengers=visible_passengers,
        candidate_links=candidate_links,
    )


@router.post(
    "/proposals/{proposal_id}/decision",
    response_model=EmailProposalDecisionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def decide_email_proposal(
    proposal_id: uuid.UUID,
    payload: DecideEmailProposalRequest,
    current_user: User = Depends(_current_email_ai_user),
    session: AsyncSession = Depends(get_db_session),
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


@router.post(
    "/deadlines/{deadline_id}/decision",
    response_model=EmailInboxDeadlineResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def decide_email_deadline(
    deadline_id: uuid.UUID,
    payload: DecideEmailDeadlineRequest,
    current_user: User = Depends(_current_email_ai_user),
    session: AsyncSession = Depends(get_db_session),
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


@router.post(
    "/drafts/{draft_id}/decision",
    response_model=EmailInboxDraftResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def decide_email_reply_draft(
    draft_id: uuid.UUID,
    payload: DecideEmailDraftRequest,
    current_user: User = Depends(_current_email_ai_user),
    session: AsyncSession = Depends(get_db_session),
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


@router.put(
    "/drafts/{draft_id}",
    response_model=EmailInboxDraftResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_email_reply_draft(
    draft_id: uuid.UUID,
    payload: UpdateEmailReplyDraftRequest,
    current_user: User = Depends(_current_email_ai_user),
    session: AsyncSession = Depends(get_db_session),
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


@router.post(
    "/analyses/{analysis_id}/feedback",
    response_model=EmailAiFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def create_email_ai_feedback(
    analysis_id: uuid.UUID,
    payload: EmailAiFeedbackRequest,
    current_user: User = Depends(_current_email_ai_user),
    session: AsyncSession = Depends(get_db_session),
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
        before_display, after_display = (
            _correction_activity_display_values(
                field_name=payload.field_name,
                original_value=feedback.original_value,
                corrected_value=feedback.corrected_value,
            )
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
                    "generated_work_invalidated": (
                        generated_work_invalidated
                    ),
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
                EmailActionProposalModel.status.in_(
                    {"proposed", "approval_required", "blocked"}
                ),
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
                EmailReplyDraftModel.status.in_(
                    {"prepared", "edited", "approved"}
                ),
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


async def _apply_typed_correction(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    payload: EmailAiFeedbackRequest,
    current_user: User,
    now: datetime,
) -> tuple[dict[str, object], dict[str, object]]:
    """Apply one owner-scoped correction and return audited before/after values."""

    correction = payload.correction
    if correction is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A typed correction is required.",
        )
    result_json = dict(analysis.result_json or {})
    field_name = payload.field_name
    original: dict[str, object]

    if field_name == "summary":
        corrected_summary = (correction.text or "").strip()
        original = {"summary": analysis.summary}
        analysis.summary = corrected_summary
        result_json["summary"] = corrected_summary
        analysis.result_json = result_json
        return original, {"summary": corrected_summary}

    if field_name == "intent":
        original = {"intent": analysis.intent}
        analysis.intent = correction.intent
        result_json["intent"] = correction.intent
        analysis.result_json = result_json
        return original, {"intent": correction.intent}

    if field_name == "priority":
        original = {"priority": analysis.priority}
        analysis.priority = correction.priority
        result_json["priority"] = correction.priority
        analysis.result_json = result_json
        return original, {"priority": correction.priority}

    if field_name == "linked_group":
        group = await _visible_correction_group(
            session,
            analysis=analysis,
            group_id=correction.group_id,
            current_user=current_user,
        )
        original = {
            "group_id": result_json.get("linked_group_id"),
            "passenger_ids": result_json.get("linked_passenger_ids", []),
        }
        result_json["linked_group_id"] = str(group.id)
        # A passenger link cannot survive a parent-group correction without
        # being explicitly reselected and revalidated.
        result_json["linked_passenger_ids"] = []
        analysis.result_json = result_json
        return original, {
            "group_id": str(group.id),
            "group_name": group.name,
            "passenger_ids": [],
        }

    if field_name == "linked_passengers":
        passenger_ids = list(dict.fromkeys(correction.passenger_ids or []))
        original = {
            "group_id": result_json.get("linked_group_id"),
            "passenger_ids": result_json.get("linked_passenger_ids", []),
        }
        if not passenger_ids:
            result_json["linked_passenger_ids"] = []
            analysis.result_json = result_json
            return original, {"passenger_ids": []}

        statement = select(PassportSubmissionModel).where(
            PassportSubmissionModel.id.in_(passenger_ids),
            PassportSubmissionModel.agency_id == analysis.agency_id,
            PassportSubmissionModel.status != "failed",
        )
        passenger_result = await session.execute(
            AuthorizationPolicy.apply_passport_visibility_scope(
                statement,
                current_user,
            )
        )
        visible_passengers = {
            passenger.id: passenger
            for passenger in passenger_result.scalars().all()
        }
        if set(visible_passengers) != set(passenger_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more selected passengers are not available.",
            )
        group_ids = {
            passenger.group_id for passenger in visible_passengers.values()
        }
        if len(group_ids) != 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Selected passengers must belong to one visible group.",
            )
        passenger_group_id = next(iter(group_ids))
        existing_group_id = _result_group_id(analysis)
        if (
            existing_group_id is not None
            and existing_group_id != passenger_group_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Selected passengers do not belong to the linked group. "
                    "Correct the group first."
                ),
            )
        group = await _visible_correction_group(
            session,
            analysis=analysis,
            group_id=passenger_group_id,
            current_user=current_user,
        )
        result_json["linked_group_id"] = str(group.id)
        result_json["linked_passenger_ids"] = [
            str(passenger_id) for passenger_id in passenger_ids
        ]
        analysis.result_json = result_json
        return original, {
            "group_id": str(group.id),
            "group_name": group.name,
            "passenger_ids": [
                str(passenger_id) for passenger_id in passenger_ids
            ],
            "passenger_names": [
                visible_passengers[passenger_id].client_name
                for passenger_id in passenger_ids
            ],
        }

    if field_name == "deadline":
        due_at = _aware_utc(correction.due_at)
        if due_at is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A timezone-aware corrected deadline is required.",
            )
        deadline: EmailDetectedDeadlineModel | None = None
        if correction.deadline_id is not None:
            deadline = (
                await session.execute(
                    select(EmailDetectedDeadlineModel)
                    .where(
                        EmailDetectedDeadlineModel.id
                        == correction.deadline_id,
                        EmailDetectedDeadlineModel.analysis_id == analysis.id,
                        EmailDetectedDeadlineModel.agency_id
                        == analysis.agency_id,
                        EmailDetectedDeadlineModel.owner_user_id
                        == analysis.owner_user_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if deadline is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="The selected deadline is not available.",
                )
            original = {
                "deadline_id": str(deadline.id),
                "due_at": (
                    _aware_utc(deadline.due_at).isoformat()
                    if deadline.due_at is not None
                    else None
                ),
                "status": deadline.status,
            }
            deadline.due_at = due_at
            deadline.confidence = 1.0
            deadline.is_ambiguous = False
            deadline.status = "review_required"
            deadline.resolution_evidence = {
                "source": "human_correction",
                "corrected_by_user_id": str(current_user.id),
                "corrected_at": now.isoformat(),
            }
            deadline.updated_at = now
        else:
            deadline_id = uuid.uuid4()
            deadline = EmailDetectedDeadlineModel(
                id=deadline_id,
                agency_id=analysis.agency_id,
                owner_user_id=analysis.owner_user_id,
                connection_id=analysis.connection_id,
                message_id=analysis.message_id,
                analysis_id=analysis.id,
                deadline_type="human_corrected",
                source_phrase="Deadline added by the mailbox owner.",
                source_fingerprint=hashlib.sha256(
                    f"human-correction:{deadline_id}".encode()
                ).hexdigest(),
                source_timezone="UTC",
                due_at=due_at,
                confidence=1.0,
                is_ambiguous=False,
                status="review_required",
                resolution_evidence={
                    "source": "human_correction",
                    "corrected_by_user_id": str(current_user.id),
                    "corrected_at": now.isoformat(),
                },
            )
            session.add(deadline)
            original = {"deadline_id": None, "due_at": None}
        await session.flush()
        return original, {
            "deadline_id": str(deadline.id),
            "due_at": due_at.isoformat(),
            "status": deadline.status,
        }

    if field_name == "notification":
        original = {
            "notification_expected": result_json.get(
                "human_notification_expected"
            ),
            "needs_attention": analysis.needs_attention,
        }
        expected = bool(correction.notification_expected)
        result_json["human_notification_expected"] = expected
        result_json["human_notification_preference_recorded_at"] = (
            now.isoformat()
        )
        analysis.result_json = result_json
        return original, {"notification_expected": expected}

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="Unsupported correction field.",
    )


async def _invalidate_generated_work_after_correction(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    field_name: str,
    current_user: User,
    now: datetime,
) -> bool:
    """Fail closed on generated work whose premises changed."""

    if field_name == "notification":
        return False
    proposal_rows = (
        await session.execute(
            select(EmailActionProposalModel)
            .where(
                EmailActionProposalModel.analysis_id == analysis.id,
                *_owner_predicates(
                    EmailActionProposalModel,
                    current_user,
                ),
                EmailActionProposalModel.status.in_(
                    {"proposed", "approval_required", "blocked"}
                ),
            )
            .with_for_update()
        )
    ).scalars().all()
    draft_rows = (
        await session.execute(
            select(EmailReplyDraftModel)
            .where(
                EmailReplyDraftModel.analysis_id == analysis.id,
                *_owner_predicates(
                    EmailReplyDraftModel,
                    current_user,
                ),
                EmailReplyDraftModel.status.in_(
                    {"prepared", "edited", "approved"}
                ),
            )
            .with_for_update()
        )
    ).scalars().all()
    for proposal in proposal_rows:
        proposal.status = "dismissed"
        proposal.revision += 1
        proposal.decision_by_user_id = current_user.id
        proposal.decision_at = now
        proposal.decision_note = (
            "Invalidated because a human corrected the AI brief."
        )
        proposal.updated_at = now
    for draft in draft_rows:
        draft.status = "dismissed"
        draft.revision += 1
        draft.edited_by_user_id = current_user.id
        draft.updated_at = now
    return bool(proposal_rows or draft_rows)


async def _visible_correction_group(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    group_id: uuid.UUID | None,
    current_user: User,
) -> ClientGroupModel:
    if group_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A group selection is required.",
        )
    statement = select(ClientGroupModel).where(
        ClientGroupModel.id == group_id,
        ClientGroupModel.agency_id == analysis.agency_id,
        ClientGroupModel.status.notin_({"archived", "deleted"}),
    )
    group = (
        await session.execute(
            AuthorizationPolicy.apply_group_visibility_scope(
                statement,
                current_user,
            )
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The selected group is not available.",
        )
    return cast(ClientGroupModel, group)


def _analysis_feedback_snapshot(
    analysis: EmailAiAnalysisModel,
) -> dict[str, object]:
    result_json = analysis.result_json or {}
    return {
        "status": analysis.status,
        "summary": analysis.summary,
        "intent": analysis.intent,
        "priority": analysis.priority,
        "needs_attention": analysis.needs_attention,
        "linked_group_id": result_json.get("linked_group_id"),
        "linked_passenger_ids": result_json.get(
            "linked_passenger_ids",
            [],
        ),
    }


_CORRECTION_ACTIVITY_VALUE_MAX_CHARS = 240


def _correction_activity_display_values(
    *,
    field_name: str,
    original_value: dict[str, object],
    corrected_value: dict[str, object],
) -> tuple[str, str]:
    """Render bounded operator-facing values from the persisted snapshots."""

    if field_name == "summary":
        return (
            _bounded_correction_text(
                original_value.get("summary"),
                empty="No summary",
            ),
            _bounded_correction_text(
                corrected_value.get("summary"),
                empty="No summary",
            ),
        )
    if field_name in {"intent", "priority"}:
        return (
            _bounded_correction_label(
                original_value.get(field_name),
                empty="Not set",
            ),
            _bounded_correction_label(
                corrected_value.get(field_name),
                empty="Not set",
            ),
        )
    if field_name == "linked_group":
        return (
            _group_snapshot_label(original_value),
            _group_snapshot_label(corrected_value),
        )
    if field_name == "linked_passengers":
        return (
            _passenger_snapshot_label(original_value),
            _passenger_snapshot_label(corrected_value),
        )
    if field_name == "deadline":
        return (
            _deadline_snapshot_label(original_value),
            _deadline_snapshot_label(corrected_value),
        )
    if field_name == "notification":
        return (
            _notification_snapshot_label(original_value),
            _notification_snapshot_label(corrected_value),
        )
    return "Previous value", "Corrected value"


def _bounded_correction_text(
    value: object,
    *,
    empty: str,
) -> str:
    if not isinstance(value, str):
        return empty
    normalized = " ".join(value.split())
    if not normalized:
        return empty
    if len(normalized) <= _CORRECTION_ACTIVITY_VALUE_MAX_CHARS:
        return normalized
    return (
        normalized[: _CORRECTION_ACTIVITY_VALUE_MAX_CHARS - 1].rstrip()
        + "…"
    )


def _bounded_correction_label(
    value: object,
    *,
    empty: str,
) -> str:
    if not isinstance(value, str):
        return empty
    return _bounded_correction_text(
        value.replace("_", " ").strip().title(),
        empty=empty,
    )


def _group_snapshot_label(value: dict[str, object]) -> str:
    name = value.get("group_name")
    if isinstance(name, str) and name.strip():
        return _bounded_correction_text(name, empty="Linked group")
    return (
        "Linked group"
        if value.get("group_id")
        else "No linked group"
    )


def _passenger_snapshot_label(value: dict[str, object]) -> str:
    names = value.get("passenger_names")
    if isinstance(names, list):
        safe_names = [
            " ".join(name.split())
            for name in names
            if isinstance(name, str) and name.strip()
        ][:20]
        if safe_names:
            return _bounded_correction_text(
                ", ".join(safe_names),
                empty="No linked passengers",
            )
    passenger_ids = value.get("passenger_ids")
    count = len(passenger_ids) if isinstance(passenger_ids, list) else 0
    if count:
        return f"{min(count, 20)} linked passenger(s)"
    return "No linked passengers"


def _deadline_snapshot_label(value: dict[str, object]) -> str:
    due_at = value.get("due_at")
    if not isinstance(due_at, str) or not due_at.strip():
        return "No deadline"
    try:
        parsed = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
    except ValueError:
        return "Previous deadline" if value.get("deadline_id") else "No deadline"
    normalized = _aware_utc(parsed)
    if normalized is None:
        return "No deadline"
    return normalized.strftime("%Y-%m-%d %H:%M UTC")


def _notification_snapshot_label(value: dict[str, object]) -> str:
    expected = value.get("notification_expected")
    if expected is True:
        return "Notification expected"
    if expected is False:
        return "No notification expected"
    return "Not specified"


def _same_instant(left: datetime, right: datetime) -> bool:
    left_utc = _aware_utc(left)
    right_utc = _aware_utc(right)
    return left_utc is not None and right_utc is not None and left_utc == right_utc


@router.post(
    "/analyses/{analysis_id}/retry",
    response_model=EmailAiRetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def retry_email_ai_analysis(
    analysis_id: uuid.UUID,
    current_user: User = Depends(_current_email_ai_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailAiRetryResponse:
    """Requeue one terminal owner-scoped analysis for a fresh bounded attempt cycle."""

    row = (
        await session.execute(
            select(
                EmailAiAnalysisModel,
                EmailConnectionModel,
                EmailMessageModel,
            )
            .join(
                EmailConnectionModel,
                and_(
                    EmailConnectionModel.id
                    == EmailAiAnalysisModel.connection_id,
                    EmailConnectionModel.agency_id
                    == EmailAiAnalysisModel.agency_id,
                    EmailConnectionModel.owner_user_id
                    == EmailAiAnalysisModel.owner_user_id,
                ),
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
            .where(
                EmailAiAnalysisModel.id == analysis_id,
                *_owner_predicates(EmailAiAnalysisModel, current_user),
            )
            .with_for_update(of=EmailAiAnalysisModel)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email intelligence was not found.",
        )
    analysis, connection, message = row
    if analysis.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a failed AI brief can be retried.",
        )

    settings = get_settings()
    if not settings.email_ai_runtime_ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Travel email analysis is not available in this deployment. "
                "No retry was queued."
            ),
        )
    if (
        not connection.ai_processing_enabled
        or connection.status not in {"active", "failing"}
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "AI assistance is not active for this mailbox. "
                "No retry was queued."
            ),
        )
    ai_enabled_at = _aware_utc(connection.ai_enabled_at)
    message_received_at = _aware_utc(message.received_at)
    if (
        ai_enabled_at is None
        or message_received_at is None
        or message_received_at < ai_enabled_at
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This email predates the mailbox's current AI opt-in. "
                "It cannot be retried under the new consent period."
            ),
        )
    if not await email_ai_policy_allows(
        session,
        agency_id=analysis.agency_id,
        owner_user_id=analysis.owner_user_id,
        connection_id=analysis.connection_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An organization, user, or mailbox safety control is "
                "blocking this retry."
            ),
        )

    previous_result = analysis.result_json or {}
    retry_generation_value = previous_result.get("manual_retry_generation", 0)
    retry_generation = (
        retry_generation_value
        if isinstance(retry_generation_value, int)
        and not isinstance(retry_generation_value, bool)
        and retry_generation_value >= 0
        else 0
    ) + 1
    if retry_generation > settings.email_ai_max_manual_retries:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The manual retry limit has been reached. "
                "An operator must review the provider or deployment failure."
            ),
        )

    now = datetime.now(tz=UTC)
    previous_error_code = analysis.last_error_code
    await session.execute(
        update(NotificationModel)
        .where(
            NotificationModel.user_id == analysis.owner_user_id,
            NotificationModel.entity_type == "email_message",
            NotificationModel.entity_id == str(analysis.message_id),
            NotificationModel.dedupe_key.like(
                f"email-ai:{analysis.id}:%"
            ),
            NotificationModel.is_read.is_(False),
        )
        .values(is_read=True, read_at=now)
        .execution_options(synchronize_session=False)
    )
    analysis.status = "pending"
    analysis.attempt_count = 0
    analysis.lease_token = None
    analysis.lease_expires_at = None
    analysis.next_attempt_at = None
    analysis.last_error_code = None
    analysis.started_at = None
    analysis.completed_at = None
    analysis.duration_ms = None
    analysis.intent = None
    analysis.priority = None
    analysis.summary = None
    analysis.confidence = None
    analysis.needs_attention = False
    analysis.context_manifest = {}
    analysis.result_json = {
        "manual_retry_generation": retry_generation,
        "manual_retry_requested_at": now.isoformat(),
        "previous_failure_code": previous_error_code,
    }
    analysis.prompt_schema_version = EMAIL_AI_SCHEMA_VERSION
    analysis.config_version = settings.gemini_config_version
    analysis.ai_model = settings.gemini_model
    analysis.updated_at = now
    session.add(
        _decision_activity_event(
            analysis=analysis,
            actor_user_id=current_user.id,
            event_key=(
                f"email-ai-analysis:{analysis.id}:retry:"
                f"{retry_generation}"
            ),
            event_type="ai_analysis_retry_requested",
            summary_code="email_ai_analysis_retry_requested",
            details={
                "analysis_id": str(analysis.id),
                "retry_generation": retry_generation,
                "max_runtime_attempts": settings.email_ai_max_attempts,
                "previous_error_code": previous_error_code,
                "external_action_performed": False,
            },
            changed_entity_type="email_ai_analysis",
            changed_entity_id=analysis.id,
            confidence=None,
        )
    )
    await session.flush()
    return EmailAiRetryResponse(
        analysis_id=analysis.id,
        status="pending",
        retry_generation=retry_generation,
        message=(
            "The AI brief is queued for a fresh bounded retry. "
            "The source email was not changed."
        ),
    )


async def _inbox_counts(
    session: AsyncSession,
    user: User,
    latest: Subquery,
    sections: dict[InboxView, ColumnElement[bool]],
) -> EmailInboxCountsResponse:
    result = await session.execute(
        select(
            func.count(EmailAiAnalysisModel.id)
            .filter(sections["needs_attention"])
            .label("needs_attention"),
            func.count(EmailAiAnalysisModel.id)
            .filter(sections["upcoming_deadlines"])
            .label("upcoming_deadlines"),
            func.count(EmailAiAnalysisModel.id)
            .filter(sections["drafts_ready"])
            .label("drafts_ready"),
            func.count(EmailAiAnalysisModel.id)
            .filter(sections["waiting"])
            .label("waiting"),
            func.count(EmailAiAnalysisModel.id)
            .filter(sections["completed_automatically"])
            .label("completed_automatically"),
            func.count(EmailAiAnalysisModel.id).label("all_activity"),
        )
        .join(
            latest,
            and_(
                latest.c.message_id == EmailAiAnalysisModel.message_id,
                latest.c.latest_created_at == EmailAiAnalysisModel.created_at,
            ),
        )
        .where(*_owner_predicates(EmailAiAnalysisModel, user))
    )
    row = result.one()
    return EmailInboxCountsResponse(
        needs_attention=int(row.needs_attention or 0),
        upcoming_deadlines=int(row.upcoming_deadlines or 0),
        drafts_ready=int(row.drafts_ready or 0),
        waiting=int(row.waiting or 0),
        completed_automatically=int(row.completed_automatically or 0),
        all_activity=int(row.all_activity or 0),
    )


async def _load_children(
    session: AsyncSession,
    analysis_ids: list[uuid.UUID],
    current_user: User,
) -> tuple[
    dict[uuid.UUID, list[EmailDetectedDeadlineModel]],
    dict[uuid.UUID, list[EmailActionProposalModel]],
    dict[uuid.UUID, EmailReplyDraftModel],
]:
    if not analysis_ids:
        return {}, {}, {}
    deadline_result = await session.execute(
        select(EmailDetectedDeadlineModel)
        .where(
            EmailDetectedDeadlineModel.analysis_id.in_(analysis_ids),
            *_owner_predicates(EmailDetectedDeadlineModel, current_user),
        )
        .order_by(EmailDetectedDeadlineModel.due_at.asc())
    )
    proposal_result = await session.execute(
        select(EmailActionProposalModel)
        .where(
            EmailActionProposalModel.analysis_id.in_(analysis_ids),
            *_owner_predicates(EmailActionProposalModel, current_user),
        )
        .order_by(EmailActionProposalModel.created_at.asc())
    )
    draft_result = await session.execute(
        select(EmailReplyDraftModel).where(
            EmailReplyDraftModel.analysis_id.in_(analysis_ids),
            *_owner_predicates(EmailReplyDraftModel, current_user),
        )
    )
    deadlines: dict[uuid.UUID, list[EmailDetectedDeadlineModel]] = {}
    for deadline in deadline_result.scalars().all():
        deadlines.setdefault(deadline.analysis_id, []).append(deadline)
    proposals: dict[uuid.UUID, list[EmailActionProposalModel]] = {}
    for proposal in proposal_result.scalars().all():
        proposals.setdefault(proposal.analysis_id, []).append(proposal)
    drafts = {draft.analysis_id: draft for draft in draft_result.scalars().all()}
    return deadlines, proposals, drafts


async def _load_visible_linked_groups(
    session: AsyncSession,
    *,
    analyses_and_messages: list[tuple[EmailAiAnalysisModel, EmailMessageModel]],
    current_user: User,
) -> dict[uuid.UUID, ClientGroupModel]:
    candidates: dict[
        uuid.UUID,
        tuple[uuid.UUID | None, uuid.UUID | None, uuid.UUID],
    ] = {}
    pair_predicates: list[ColumnElement[bool]] = []
    for analysis, message in analyses_and_messages:
        ai_group_id = _result_group_id(analysis)
        message_group_id = message.group_id
        primary_id = ai_group_id or message_group_id
        fallback_id = message_group_id if ai_group_id is not None else None
        candidates[analysis.id] = (
            primary_id,
            fallback_id,
            analysis.agency_id,
        )
        for group_id in (ai_group_id, message_group_id):
            if group_id is None:
                continue
            pair_predicates.append(
                and_(
                    ClientGroupModel.id == group_id,
                    ClientGroupModel.agency_id == analysis.agency_id,
                )
            )
    if not pair_predicates:
        return {}

    statement = select(ClientGroupModel).where(or_(*pair_predicates))
    result = await session.execute(
        AuthorizationPolicy.apply_group_visibility_scope(
            statement,
            current_user,
        )
    )
    visible_by_pair = {(group.agency_id, group.id): group for group in result.scalars().all()}
    visible_by_analysis: dict[uuid.UUID, ClientGroupModel] = {}
    for analysis_id, (primary_id, fallback_id, agency_id) in candidates.items():
        group = visible_by_pair.get((agency_id, primary_id)) if primary_id is not None else None
        if group is None and fallback_id is not None:
            group = visible_by_pair.get((agency_id, fallback_id))
        if group is not None:
            visible_by_analysis[analysis_id] = group
    return visible_by_analysis


def _result_group_id(analysis: EmailAiAnalysisModel) -> uuid.UUID | None:
    result_json = analysis.result_json or {}
    value = result_json.get("linked_group_id")
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def _load_visible_linked_passengers(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    current_user: User,
) -> list[tuple[uuid.UUID, str]]:
    result_json = analysis.result_json or {}
    raw_ids = result_json.get("linked_passenger_ids", [])
    if not isinstance(raw_ids, list):
        return []
    linked_ids: list[uuid.UUID] = []
    for value in raw_ids[:100]:
        try:
            linked_ids.append(uuid.UUID(str(value)))
        except (TypeError, ValueError):
            continue
    if not linked_ids:
        return []
    statement = select(
        PassportSubmissionModel.id,
        PassportSubmissionModel.client_name,
    ).where(
        PassportSubmissionModel.id.in_(linked_ids),
        PassportSubmissionModel.agency_id == analysis.agency_id,
    )
    visible_result = await session.execute(
        AuthorizationPolicy.apply_passport_visibility_scope(
            statement,
            current_user,
        )
    )
    visible = {row.id: row.client_name for row in visible_result.all()}
    return [
        (passenger_id, visible[passenger_id])
        for passenger_id in linked_ids
        if passenger_id in visible
    ]


async def _load_visible_candidate_links(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    current_user: User,
    canonical_passenger_ids: set[uuid.UUID],
) -> list[EmailCandidateLinkResponse]:
    """Resolve provider aliases back to currently visible, live records only."""

    result_json = analysis.result_json or {}
    raw_links = result_json.get("candidate_links")
    manifest_aliases = (analysis.context_manifest or {}).get("aliases")
    if not isinstance(raw_links, list) or not isinstance(manifest_aliases, dict):
        return []

    aliases = cast(dict[object, object], manifest_aliases)
    resolved: list[ResolvedCandidateLink] = []
    seen: set[tuple[CandidateEntityType, uuid.UUID]] = set()
    for raw_link in raw_links[:24]:
        candidate = _parse_candidate_link(raw_link, aliases)
        if candidate is None:
            continue
        entity_type, entity_id, confidence, rationale = candidate
        key = (entity_type, entity_id)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(candidate)
    if not resolved:
        return []

    group_ids = [entity_id for entity_type, entity_id, _, _ in resolved if entity_type == "group"]
    passenger_ids = [
        entity_id for entity_type, entity_id, _, _ in resolved if entity_type == "passenger"
    ]
    visible_names: dict[tuple[CandidateEntityType, uuid.UUID], str] = {}
    if group_ids:
        group_statement = select(
            ClientGroupModel.id,
            ClientGroupModel.name,
        ).where(
            ClientGroupModel.id.in_(group_ids),
            ClientGroupModel.agency_id == analysis.agency_id,
            ClientGroupModel.status.notin_({"archived", "deleted"}),
        )
        group_result = await session.execute(
            AuthorizationPolicy.apply_group_visibility_scope(
                group_statement,
                current_user,
            )
        )
        visible_names.update(
            {
                ("group", row.id): row.name
                for row in group_result.all()
                if isinstance(row.name, str) and row.name.strip()
            }
        )
    if passenger_ids:
        passenger_statement = select(
            PassportSubmissionModel.id,
            PassportSubmissionModel.client_name,
        ).where(
            PassportSubmissionModel.id.in_(passenger_ids),
            PassportSubmissionModel.agency_id == analysis.agency_id,
            PassportSubmissionModel.status != "failed",
        )
        passenger_result = await session.execute(
            AuthorizationPolicy.apply_passport_visibility_scope(
                passenger_statement,
                current_user,
            )
        )
        visible_names.update(
            {
                ("passenger", row.id): row.client_name
                for row in passenger_result.all()
                if isinstance(row.client_name, str) and row.client_name.strip()
            }
        )

    canonical_group_id = _result_group_id(analysis)
    return [
        EmailCandidateLinkResponse(
            entity_type=entity_type,
            entity_id=entity_id,
            name=visible_names[(entity_type, entity_id)],
            confidence=confidence,
            rationale=rationale,
            canonical=(
                entity_id == canonical_group_id
                if entity_type == "group"
                else entity_id in canonical_passenger_ids
            ),
        )
        for entity_type, entity_id, confidence, rationale in resolved
        if (entity_type, entity_id) in visible_names
    ]


def _parse_candidate_link(
    raw_link: object,
    aliases: dict[object, object],
) -> ResolvedCandidateLink | None:
    """Validate one provider candidate before any tenant-scoped lookup."""

    if not isinstance(raw_link, dict):
        return None
    candidate = cast(dict[object, object], raw_link)
    alias = candidate.get("alias")
    confidence = candidate.get("confidence")
    rationale = candidate.get("rationale")
    alias_record = aliases.get(alias) if isinstance(alias, str) else None
    if not isinstance(alias_record, dict):
        return None
    alias_values = cast(dict[object, object], alias_record)
    entity_type_value = alias_values.get("entity_type")
    if (
        entity_type_value not in {"group", "passenger"}
        or not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= float(confidence) <= 1
        or not isinstance(rationale, str)
    ):
        return None
    try:
        entity_id = uuid.UUID(str(alias_values.get("entity_id")))
    except (TypeError, ValueError):
        return None
    entity_type: CandidateEntityType = "group" if entity_type_value == "group" else "passenger"
    return entity_type, entity_id, float(confidence), rationale.strip()[:320]


async def _refresh_analysis_attention(
    session: AsyncSession,
    analysis: EmailAiAnalysisModel,
) -> None:
    open_proposals = int(
        await session.scalar(
            select(func.count(EmailActionProposalModel.id)).where(
                EmailActionProposalModel.analysis_id == analysis.id,
                EmailActionProposalModel.agency_id == analysis.agency_id,
                EmailActionProposalModel.owner_user_id == analysis.owner_user_id,
                EmailActionProposalModel.status.in_({"proposed", "approval_required", "blocked"}),
            )
        )
        or 0
    )
    review_deadlines = int(
        await session.scalar(
            select(func.count(EmailDetectedDeadlineModel.id)).where(
                EmailDetectedDeadlineModel.analysis_id == analysis.id,
                EmailDetectedDeadlineModel.agency_id == analysis.agency_id,
                EmailDetectedDeadlineModel.owner_user_id == analysis.owner_user_id,
                EmailDetectedDeadlineModel.status == "review_required",
            )
        )
        or 0
    )
    result = analysis.result_json or {}
    settings = get_settings()
    candidate_links = result.get("candidate_links")
    low_confidence_link = bool(
        isinstance(candidate_links, list)
        and any(
            isinstance(link, dict)
            and isinstance(link.get("confidence"), (int, float))
            and float(link["confidence"]) < settings.email_ai_auto_confidence_threshold
            for link in candidate_links
        )
    )
    intrinsic_review = bool(
        not result.get("human_review_confirmed")
        and (
            result.get("relevance") == "possibly_relevant"
            or analysis.priority == "urgent"
            or analysis.intent in {"cancellation", "payment"}
            or (
                analysis.confidence is not None
                and analysis.confidence < settings.email_ai_auto_confidence_threshold
            )
            or low_confidence_link
            or result.get("candidate_ambiguity") is True
            or result.get("human_correction_pending") is True
            or _has_high_risk(result.get("risks"))
        )
    )
    analysis.needs_attention = bool(open_proposals or review_deadlines or intrinsic_review)
    if analysis.status == "review_required" and not analysis.needs_attention:
        analysis.status = "completed"
    analysis.updated_at = datetime.now(tz=UTC)
    await session.flush()


def _has_high_risk(value: object) -> bool:
    if not isinstance(value, list):
        return False
    return any(
        isinstance(item, dict) and item.get("level") in {"high", "critical"} for item in value
    )


def _decision_activity_event(
    *,
    analysis: EmailAiAnalysisModel,
    actor_user_id: uuid.UUID,
    event_key: str,
    event_type: str,
    summary_code: str,
    details: dict[str, object],
    changed_entity_type: str,
    changed_entity_id: uuid.UUID,
    confidence: float | None,
) -> EmailActivityEventModel:
    return EmailActivityEventModel(
        agency_id=analysis.agency_id,
        owner_user_id=analysis.owner_user_id,
        connection_id=analysis.connection_id,
        message_id=analysis.message_id,
        event_key=event_key,
        event_type=event_type,
        stage="info",
        actor_type="user",
        actor_user_id=actor_user_id,
        summary_code=summary_code,
        details=details,
        ai_used=True,
        ai_provider=analysis.ai_provider,
        ai_model=analysis.ai_model,
        confidence=confidence,
        changed_entity_type=changed_entity_type,
        changed_entity_id=changed_entity_id,
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


def _priority_order() -> ColumnElement[int]:
    return case(
        (EmailAiAnalysisModel.priority == "urgent", 0),
        (EmailAiAnalysisModel.priority == "high", 1),
        (EmailAiAnalysisModel.priority == "normal", 2),
        else_=3,
    )


def _priority_rank(priority: str | None) -> int:
    return {"urgent": 0, "high": 1, "normal": 2}.get(priority or "", 3)


def _encode_cursor(
    priority: str | None,
    updated_at: datetime,
    analysis_id: uuid.UUID,
) -> str:
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    payload = json.dumps(
        {
            "priority_rank": _priority_rank(priority),
            "updated_at": updated_at.isoformat(),
            "id": str(analysis_id),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[int, datetime, uuid.UUID]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
        priority_rank = int(payload["priority_rank"])
        updated_at = datetime.fromisoformat(payload["updated_at"])
        analysis_id = uuid.UUID(payload["id"])
        if priority_rank not in {0, 1, 2, 3} or updated_at.tzinfo is None:
            raise ValueError
        return priority_rank, updated_at, analysis_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid inbox cursor.",
        ) from exc
