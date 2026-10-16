"""Tenant-authorized history of every send, independently of message type."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.whatsapp_delivery_status import WHATSAPP_ACCEPTED_STATUSES
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.whatsapp_history_queries import (
    escaped_history_search,
    history_aggregates,
    history_predicates,
    history_status,
    message_history_statement,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ROLES,
    WHATSAPP_STALE_CLAIM_AGE,
    _agency_filter,
)
from app.presentation.api.v1.schemas.whatsapp_history_schemas import (
    HistoryFilter,
    MessageHistoryCounts,
    MessageHistoryEntry,
    MessageHistoryPage,
    MessageHistoryRecipient,
    MessageHistoryRecipientPage,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()
Log = WhatsAppMessageLogModel
Recipient = WhatsAppBroadcastRecipientModel


async def _authorized_group(
    session: AsyncSession, group_id: uuid.UUID, user: User
) -> WhatsAppBroadcastGroupModel:
    group = await session.scalar(
        select(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(user),
        )
    )
    if group is None:
        raise HTTPException(404, "WhatsApp broadcast not found")
    return group


def _counts(row: Any) -> MessageHistoryCounts:
    return MessageHistoryCounts(
        **{key: int(row[key] or 0) for key in MessageHistoryCounts.model_fields}
    )


@router.get("/groups/{group_id}/messages", response_model=MessageHistoryPage)
async def list_broadcast_messages(
    group_id: uuid.UUID,
    q: str = Query(default="", max_length=120),
    message_type: str | None = Query(default=None, max_length=64),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> MessageHistoryPage:
    await _authorized_group(session, group_id, current_user)
    cutoff = datetime.now(UTC) - WHATSAPP_STALE_CLAIM_AGE
    statement = message_history_statement(group_id, cutoff)
    if message_type:
        statement = statement.where(Log.message_type == message_type)
    if q.strip():
        pattern = escaped_history_search(q.strip())
        statement = statement.having(
            func.max(
                case(
                    (
                        or_(
                            Log.message_type.ilike(pattern, escape="\\"),
                            Log.rendered_message.ilike(pattern, escape="\\"),
                        ),
                        1,
                    ),
                    else_=0,
                )
            )
            == 1
        )
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    result = await session.execute(
        statement.order_by(
            func.min(Log.created_at).desc(),
            func.coalesce(Log.batch_id, Log.id).desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    return MessageHistoryPage(
        items=[
            MessageHistoryEntry(
                id=row["id"],
                message_type=row["message_type"],
                message_preview=(row["message_preview"] or "")[:240],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                counts=_counts(row),
            )
            for row in result.mappings()
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/groups/{group_id}/messages/{message_id}", response_model=MessageHistoryEntry)
async def get_broadcast_message(
    group_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> MessageHistoryEntry:
    await _authorized_group(session, group_id, current_user)
    result = await session.execute(
        message_history_statement(
            group_id,
            datetime.now(UTC) - WHATSAPP_STALE_CLAIM_AGE,
        ).where(func.coalesce(Log.batch_id, Log.id) == message_id)
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "This message was not found in this broadcast")
    return MessageHistoryEntry(
        id=row["id"],
        message_type=row["message_type"],
        message_preview=(row["message_preview"] or "")[:240],
        rendered_message=row["message_preview"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        counts=_counts(row),
    )


@router.get(
    "/groups/{group_id}/messages/{message_id}/recipients",
    response_model=MessageHistoryRecipientPage,
)
async def list_message_recipients(
    group_id: uuid.UUID,
    message_id: uuid.UUID,
    status_filter: HistoryFilter = Query(default="all"),
    q: str = Query(default="", max_length=120),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> MessageHistoryRecipientPage:
    group = await _authorized_group(session, group_id, current_user)
    cutoff = datetime.now(UTC) - WHATSAPP_STALE_CLAIM_AGE
    predicates = (
        Log.broadcast_group_id == group_id,
        func.coalesce(Log.batch_id, Log.id) == message_id,
    )
    count_result = await session.execute(select(*history_aggregates(cutoff)).where(*predicates))
    counts = _counts(count_result.mappings().one())
    if counts.all == 0:
        raise HTTPException(404, "This message was not found in this broadcast")
    statement = (
        select(Log, Recipient, history_status(cutoff).label("display_status"))
        .join(
            Recipient,
            Recipient.id == Log.recipient_id,
        )
        .where(
            *predicates,
            Recipient.broadcast_group_id == group_id,
            Recipient.agency_id == group.agency_id,
        )
    )
    if status_filter != "all":
        statement = statement.where(history_predicates(cutoff)[status_filter])
    if q.strip():
        pattern = escaped_history_search(q.strip())
        statement = statement.where(
            or_(
                Recipient.name.ilike(pattern, escape="\\"),
                Log.normalized_phone_number.ilike(pattern, escape="\\"),
                Recipient.normalized_phone_number.ilike(pattern, escape="\\"),
            )
        )
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    result = await session.execute(
        statement.order_by(
            Recipient.name.asc().nulls_last(),
            Log.id.asc(),
        )
        .offset(offset)
        .limit(limit)
    )
    return MessageHistoryRecipientPage(
        items=[
            MessageHistoryRecipient(
                message_log_id=log.id,
                recipient_id=recipient.id,
                name=recipient.name,
                phone_number=log.normalized_phone_number or recipient.normalized_phone_number,
                current_phone_number=recipient.normalized_phone_number,
                status=display_status,
                error_message=log.error_message,
                rendered_message=log.rendered_message,
                updated_at=log.status_updated_at,
                removed=recipient.removed_at is not None,
                can_resend=group.archived_at is None
                and recipient.removed_at is None
                and display_status in WHATSAPP_ACCEPTED_STATUSES | {"failed"},
            )
            for log, recipient, display_status in result
        ],
        total=total,
        offset=offset,
        limit=limit,
        counts=counts,
    )
