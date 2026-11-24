"""Reads for the owner-scoped email inbox."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.database.email_models import EmailConnectionModel, EmailMessageModel
from app.presentation.api.v1.routes import email_ai_inbox_cursor as _cursor
from app.presentation.api.v1.routes import email_ai_inbox_queries as _queries
from app.presentation.api.v1.routes import email_ai_inbox_responses as _responses
from app.presentation.api.v1.routes import email_ai_inbox_scope as _scope
from app.presentation.api.v1.routes import email_ai_inbox_visibility as _visibility
from app.presentation.api.v1.routes.email_ai_inbox_types import InboxView as InboxView
from app.presentation.api.v1.routes.email_ai_inbox_types import SettingsProvider
from app.presentation.api.v1.schemas.email_ai_schemas import (
    EmailInboxResponse,
    EmailIntelligenceResponse,
)

_latest_analyses = _queries._latest_analyses
_section_predicates = _queries._section_predicates
_priority_order = _queries._priority_order
_load_children = _queries._load_children
_inbox_counts = _queries._inbox_counts
_owner_predicates = _scope._owner_predicates
_load_visible_candidate_links = _visibility._load_visible_candidate_links
_load_visible_linked_groups = _visibility._load_visible_linked_groups
_load_visible_linked_passengers = _visibility._load_visible_linked_passengers
_inbox_item = _responses._inbox_item
_intelligence_response = _responses._intelligence_response
_decode_cursor = _cursor._decode_cursor
_encode_cursor = _cursor._encode_cursor


async def email_operations_inbox(
    view: InboxView,
    cursor: str | None,
    limit: int,
    current_user: User,
    session: AsyncSession,
    get_settings: SettingsProvider,
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
                latest.c.analysis_id == EmailAiAnalysisModel.id,
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


async def email_message_intelligence(
    message_id: uuid.UUID,
    current_user: User,
    session: AsyncSession,
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
        .order_by(EmailAiAnalysisModel.created_at.desc(), EmailAiAnalysisModel.id.desc())
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
