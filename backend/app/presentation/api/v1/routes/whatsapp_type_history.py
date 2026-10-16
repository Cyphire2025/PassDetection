"""Additional type-level reports; the existing per-send history stays intact."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import WhatsAppBroadcastRecipientModel as Recipient
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.whatsapp_history import _authorized_group, _counts
from app.presentation.api.v1.routes.whatsapp_history_queries import (
    escaped_history_search,
    history_aggregates,
    history_predicates,
)
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ROLES, WHATSAPP_STALE_CLAIM_AGE
from app.presentation.api.v1.routes.whatsapp_type_history_queries import (
    HISTORY_TYPES,
    numbered_type_versions,
    type_coverage_statistics,
    type_recipient_scope,
    type_send_statistics,
)
from app.presentation.api.v1.schemas.whatsapp_history_schemas import (
    HistoryFilter,
    MessageHistoryCounts,
)
from app.presentation.api.v1.schemas.whatsapp_type_history_schemas import (
    MessageTypeRecipient,
    MessageTypeRecipientPage,
    MessageTypeSummary,
    MessageTypeVersion,
    MessageTypeVersionPage,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()
TypeKey = Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


@router.get("/groups/{group_id}/message-types", response_model=list[MessageTypeSummary])
async def list_message_types(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[MessageTypeSummary]:
    group = await _authorized_group(session, group_id, current_user)
    cutoff = datetime.now(UTC) - WHATSAPP_STALE_CLAIM_AGE
    recipient_count = int(
        await session.scalar(
            select(func.count())
            .select_from(Recipient)
            .where(
                Recipient.broadcast_group_id == group_id,
                Recipient.agency_id == group.agency_id,
                Recipient.removed_at.is_(None),
            )
        )
        or 0
    )
    sends = {
        row["message_type"]: row
        for row in (
            await session.execute(type_send_statistics(group_id, group.agency_id))
        ).mappings()
    }
    coverage = {
        row["message_type"]: row
        for row in (
            await session.execute(type_coverage_statistics(group_id, group.agency_id, cutoff))
        ).mappings()
    }
    output = []
    for message_type in (*HISTORY_TYPES, *sorted(sends.keys() - set(HISTORY_TYPES))):
        stats = sends.get(message_type, {})
        counts = (
            _counts(coverage[message_type]) if message_type in coverage else MessageHistoryCounts()
        )
        never = max(0, recipient_count - counts.all)
        counts.not_sent += never
        counts.all = recipient_count
        output.append(
            MessageTypeSummary(
                message_type=message_type,
                counts=counts,
                never_attempted=never,
                **{
                    key: int(stats.get(key, 0))
                    for key in (
                        "send_count",
                        "version_count",
                        "legacy_record_count",
                        "total_attempts",
                        "accepted_attempts",
                    )
                },
                last_sent_at=stats.get("last_sent_at"),
            )
        )
    return output


@router.get(
    "/groups/{group_id}/message-types/{message_type}/versions",
    response_model=MessageTypeVersionPage,
)
async def list_type_versions(
    group_id: uuid.UUID,
    message_type: TypeKey,
    q: str = Query(default="", max_length=120),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> MessageTypeVersionPage:
    group = await _authorized_group(session, group_id, current_user)
    canonical = "document_update" if message_type == "update" else message_type
    rows = numbered_type_versions(
        group_id, group.agency_id, canonical, datetime.now(UTC) - WHATSAPP_STALE_CLAIM_AGE
    )
    statement = select(rows)
    if q.strip():
        statement = statement.where(
            rows.c.message_preview.ilike(escaped_history_search(q.strip()), escape="\\")
        )
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    result = await session.execute(
        statement.order_by(rows.c.created_at.desc(), rows.c.id.desc()).offset(offset).limit(limit)
    )
    return MessageTypeVersionPage(
        items=[
            MessageTypeVersion(
                id=row["id"],
                message_type=row["message_type"],
                message_preview=(row["message_preview"] or "")[:240],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                counts=_counts(row),
                version_number=row["version_number"],
            )
            for row in result.mappings()
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/groups/{group_id}/message-types/{message_type}/recipients",
    response_model=MessageTypeRecipientPage,
)
async def list_type_recipients(
    group_id: uuid.UUID,
    message_type: TypeKey,
    status_filter: HistoryFilter = Query(default="all"),
    q: str = Query(default="", max_length=120),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> MessageTypeRecipientPage:
    group = await _authorized_group(session, group_id, current_user)
    cutoff = datetime.now(UTC) - WHATSAPP_STALE_CLAIM_AGE
    canonical = "document_update" if message_type == "update" else message_type
    rows = type_recipient_scope(group_id, group.agency_id, canonical, cutoff)
    counts = _counts(
        (await session.execute(select(*history_aggregates(cutoff, rows.c.status)))).mappings().one()
    )
    statement = select(rows)
    if status_filter != "all":
        statement = statement.where(history_predicates(cutoff, rows.c.status)[status_filter])
    if q.strip():
        pattern = escaped_history_search(q.strip())
        statement = statement.where(
            or_(
                rows.c.name.ilike(pattern, escape="\\"),
                rows.c.phone_number.ilike(pattern, escape="\\"),
            )
        )
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    result = await session.execute(
        statement.order_by(rows.c.name.asc().nulls_last(), rows.c.recipient_id)
        .offset(offset)
        .limit(limit)
    )
    return MessageTypeRecipientPage(
        items=[MessageTypeRecipient(**row) for row in result.mappings()],
        total=total,
        offset=offset,
        limit=limit,
        counts=counts,
    )
