"""Owner-only API for the AI Travel Operations Inbox."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_ai_models import (
    EmailAiAnalysisModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes import (
    email_ai_inbox_activity as _activity,
)
from app.presentation.api.v1.routes import email_ai_inbox_attention as _attention
from app.presentation.api.v1.routes import email_ai_inbox_corrections as _corrections
from app.presentation.api.v1.routes import (
    email_ai_inbox_cursor as _cursor,
)
from app.presentation.api.v1.routes import email_ai_inbox_decisions as _decisions
from app.presentation.api.v1.routes import email_ai_inbox_feedback as _feedback
from app.presentation.api.v1.routes import email_ai_inbox_queries as _queries
from app.presentation.api.v1.routes import email_ai_inbox_reads as _reads
from app.presentation.api.v1.routes import (
    email_ai_inbox_responses as _responses,
)
from app.presentation.api.v1.routes import email_ai_inbox_retry as _retry
from app.presentation.api.v1.routes import email_ai_inbox_scope as _scope
from app.presentation.api.v1.routes import email_ai_inbox_visibility as _visibility
from app.presentation.api.v1.routes.email_ai_inbox_scope import (
    _OwnerScopedModel as _OwnerScopedModel,
)
from app.presentation.api.v1.routes.email_ai_inbox_types import InboxView as InboxView
from app.presentation.api.v1.routes.email_ai_inbox_types import ProposalAction as ProposalAction
from app.presentation.api.v1.routes.email_ai_inbox_visibility import (
    CandidateEntityType as CandidateEntityType,
)
from app.presentation.api.v1.routes.email_ai_inbox_visibility import (
    ResolvedCandidateLink as ResolvedCandidateLink,
)
from app.presentation.api.v1.schemas.email_ai_schemas import (
    DecideEmailDeadlineRequest,
    DecideEmailDraftRequest,
    DecideEmailProposalRequest,
    EmailAiFeedbackRequest,
    EmailAiFeedbackResponse,
    EmailAiRetryResponse,
    EmailInboxDeadlineResponse,
    EmailInboxDraftResponse,
    EmailInboxResponse,
    EmailIntelligenceResponse,
    EmailProposalDecisionResponse,
    UpdateEmailReplyDraftRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

# Keep the established facade imports and patch points available.
_inbox_counts = _queries._inbox_counts
_latest_analyses = _queries._latest_analyses
_load_children = _queries._load_children
_priority_order = _queries._priority_order
_section_predicates = _queries._section_predicates
_has_high_risk = _attention._has_high_risk
_owner_predicates = _scope._owner_predicates
_apply_typed_correction = _corrections._apply_typed_correction
_invalidate_generated_work_after_correction = (
    _corrections._invalidate_generated_work_after_correction
)
_visible_correction_group = _corrections._visible_correction_group
_load_visible_candidate_links = _visibility._load_visible_candidate_links
_load_visible_linked_groups = _visibility._load_visible_linked_groups
_load_visible_linked_passengers = _visibility._load_visible_linked_passengers
_parse_candidate_link = _visibility._parse_candidate_link
_result_group_id = _responses._result_group_id
_aware_utc = _responses._aware_utc
_same_instant = _responses._same_instant
_deadline_response = _responses._deadline_response
_draft_response = _responses._draft_response
_inbox_item = _responses._inbox_item
_intelligence_response = _responses._intelligence_response
_proposal_response = _responses._proposal_response
_safe_risk_strings = _responses._safe_risk_strings
_safe_strings = _responses._safe_strings
_CORRECTION_ACTIVITY_VALUE_MAX_CHARS = _activity._CORRECTION_ACTIVITY_VALUE_MAX_CHARS
_analysis_feedback_snapshot = _activity._analysis_feedback_snapshot
_bounded_correction_label = _activity._bounded_correction_label
_bounded_correction_text = _activity._bounded_correction_text
_correction_activity_display_values = _activity._correction_activity_display_values
_deadline_snapshot_label = _activity._deadline_snapshot_label
_decision_activity_event = _activity._decision_activity_event
_group_snapshot_label = _activity._group_snapshot_label
_notification_snapshot_label = _activity._notification_snapshot_label
_passenger_snapshot_label = _activity._passenger_snapshot_label
_decode_cursor = _cursor._decode_cursor
_encode_cursor = _cursor._encode_cursor
_priority_rank = _cursor._priority_rank

router = APIRouter()

EMAIL_AI_INBOX_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
]
_current_email_ai_user = require_role(EMAIL_AI_INBOX_ROLES)


@router.get("/inbox", response_model=EmailInboxResponse)
async def email_operations_inbox(
    view: InboxView = "needs_attention",
    cursor: str | None = Query(default=None, max_length=1000),
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(_current_email_ai_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailInboxResponse:
    return await _reads.email_operations_inbox(
        view=view,
        cursor=cursor,
        limit=limit,
        current_user=current_user,
        session=session,
        get_settings=get_settings,
    )


@router.get(
    "/messages/{message_id}/intelligence",
    response_model=EmailIntelligenceResponse,
)
async def email_message_intelligence(
    message_id: uuid.UUID,
    current_user: User = Depends(_current_email_ai_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailIntelligenceResponse:
    return await _reads.email_message_intelligence(
        message_id=message_id,
        current_user=current_user,
        session=session,
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
    return await _decisions.decide_email_proposal(
        proposal_id=proposal_id,
        payload=payload,
        current_user=current_user,
        session=session,
        _refresh_analysis_attention=_refresh_analysis_attention,
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
    return await _decisions.decide_email_deadline(
        deadline_id=deadline_id,
        payload=payload,
        current_user=current_user,
        session=session,
        _refresh_analysis_attention=_refresh_analysis_attention,
    )


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
    return await _decisions.decide_email_reply_draft(
        draft_id=draft_id,
        payload=payload,
        current_user=current_user,
        session=session,
        _refresh_analysis_attention=_refresh_analysis_attention,
    )


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
    return await _decisions.update_email_reply_draft(
        draft_id=draft_id,
        payload=payload,
        current_user=current_user,
        session=session,
        _refresh_analysis_attention=_refresh_analysis_attention,
    )


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
    return await _feedback.create_email_ai_feedback(
        analysis_id=analysis_id,
        payload=payload,
        current_user=current_user,
        session=session,
        _refresh_analysis_attention=_refresh_analysis_attention,
    )


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
    return await _retry.retry_email_ai_analysis(
        analysis_id=analysis_id,
        current_user=current_user,
        session=session,
        get_settings=get_settings,
    )


async def _refresh_analysis_attention(
    session: AsyncSession,
    analysis: EmailAiAnalysisModel,
) -> None:
    return await _attention._refresh_analysis_attention(
        session=session,
        analysis=analysis,
        get_settings=get_settings,
    )
