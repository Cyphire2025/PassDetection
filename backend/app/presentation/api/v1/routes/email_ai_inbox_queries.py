"""Queries for the owner-scoped email inbox."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from app.domain.entities.entities import User
from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.presentation.api.v1.routes import email_ai_inbox_scope as _scope
from app.presentation.api.v1.routes.email_ai_inbox_types import InboxView as InboxView
from app.presentation.api.v1.schemas.email_ai_schemas import EmailInboxCountsResponse

_owner_predicates = _scope._owner_predicates


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
    ranked = (
        select(
            EmailAiAnalysisModel.id.label("analysis_id"),
            EmailAiAnalysisModel.message_id.label("message_id"),
            EmailAiAnalysisModel.created_at.label("latest_created_at"),
            func.row_number()
            .over(
                partition_by=EmailAiAnalysisModel.message_id,
                order_by=(
                    EmailAiAnalysisModel.created_at.desc(),
                    EmailAiAnalysisModel.id.desc(),
                ),
            )
            .label("position"),
        )
        .where(*_owner_predicates(EmailAiAnalysisModel, user))
        .subquery()
    )
    return (
        select(
            ranked.c.analysis_id,
            ranked.c.message_id,
            ranked.c.latest_created_at,
        )
        .where(ranked.c.position == 1)
        .subquery()
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
            func.count(EmailAiAnalysisModel.id).filter(sections["waiting"]).label("waiting"),
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
                latest.c.analysis_id == EmailAiAnalysisModel.id,
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


def _priority_order() -> ColumnElement[int]:
    return case(
        (EmailAiAnalysisModel.priority == "urgent", 0),
        (EmailAiAnalysisModel.priority == "high", 1),
        (EmailAiAnalysisModel.priority == "normal", 2),
        else_=3,
    )
