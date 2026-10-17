"""Company-local committed publication sequence and reference-only change pages.

A counter row serializes one company's bounded publish batch. Sequences become
visible atomically with events, so a late source transaction cannot be missed by
an already issued checkpoint. Queries examine at most 101 events per request,
including hidden groups; empty filtered pages may therefore still have more.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import require_company, visible_company_groups
from app.application.mcp.read_cursor import MCPReadCursor
from app.domain.entities.entities import User
from app.infrastructure.database.traveller_reuse_models import (
    TravellerChangeEventModel,
    TravellerChangeFeedModel,
    TravellerParticipationModel,
)


async def publish_change_page(session: AsyncSession, *, page_size: int = 100) -> int:
    if not 1 <= page_size <= 100:
        raise ValueError("Publish page size must be between 1 and 100")
    head = (await session.execute(select(TravellerChangeEventModel.agency_id, TravellerChangeEventModel.company_id).where(
        TravellerChangeEventModel.feed_sequence.is_(None),
    ).order_by(TravellerChangeEventModel.created_at, TravellerChangeEventModel.id).limit(1))).one_or_none()
    if head is None:
        return 0
    insert = pg_insert if session.bind is not None and session.bind.dialect.name == "postgresql" else sqlite_insert
    await session.execute(insert(TravellerChangeFeedModel).values(agency_id=head.agency_id,
        company_id=head.company_id, last_sequence=0).on_conflict_do_nothing(index_elements=["company_id"]))
    feed = await session.scalar(select(TravellerChangeFeedModel).where(
        TravellerChangeFeedModel.company_id == head.company_id,
        TravellerChangeFeedModel.agency_id == head.agency_id,
    ).with_for_update().execution_options(populate_existing=True))
    assert feed is not None
    rows = (await session.scalars(select(TravellerChangeEventModel).where(
        TravellerChangeEventModel.agency_id == head.agency_id,
        TravellerChangeEventModel.company_id == head.company_id,
        TravellerChangeEventModel.feed_sequence.is_(None),
    ).order_by(TravellerChangeEventModel.created_at, TravellerChangeEventModel.id)
        .limit(page_size).with_for_update())).all()
    for row in rows:
        feed.last_sequence += 1
        row.feed_sequence = feed.last_sequence
    await session.flush()
    return len(rows)


async def read_changes(
    session: AsyncSession, *, user: User, company_id: uuid.UUID, agency_id: uuid.UUID | None,
    checkpoint: str | None, page_size: int, signing_secret: str,
) -> dict[str, object]:
    if not 1 <= page_size <= 100:
        raise ValueError("Change page size must be between 1 and 100")
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    codec = MCPReadCursor(signing_secret, "company-change-feed-v1")
    state = codec.read(checkpoint, {"actor": str(user.id), "agency": str(company.agency_id), "company": str(company.id)})
    after_sequence = state.get("sequence", 0)
    if not isinstance(after_sequence, int) or isinstance(after_sequence, bool) or after_sequence < 0:
        raise ValueError("Invalid change checkpoint")
    groups = visible_company_groups(user, company.agency_id, company.id).subquery()
    membership = exists(select(TravellerParticipationModel.id).join(groups,
        groups.c.id == TravellerParticipationModel.group_id).where(
        TravellerParticipationModel.agency_id == company.agency_id,
        TravellerParticipationModel.company_id == company.id,
        TravellerParticipationModel.traveller_id == TravellerChangeEventModel.traveller_id,
    ))
    rows = list((await session.execute(select(TravellerChangeEventModel, membership.label("visible")).where(
        TravellerChangeEventModel.agency_id == company.agency_id,
        TravellerChangeEventModel.company_id == company.id,
        TravellerChangeEventModel.feed_sequence > after_sequence,
    ).order_by(TravellerChangeEventModel.feed_sequence).limit(page_size + 1))).all())
    has_more, rows = len(rows) > page_size, rows[:page_size]
    events = [{"id": row.id, "sequence": row.feed_sequence,
        "kind": "added" if row.event_type == "added" else "removed" if row.event_type in {"removed", "reuse_revoked"} else "changed",
        "record_type": "document" if row.event_type in {"document_promoted", "document_blocked"} else "profile" if row.event_type in {"contact_recovered", "reuse_revoked"} else "participation",
        "record_id": row.aggregate_id, "revision": row.aggregate_revision,
        "reason_code": row.reason_code, "occurred_at": row.created_at} for row, visible in rows if visible]
    # Incremental consumers need a durable checkpoint between daily runs. Live
    # actor/group authorization is checked on every page independently of TTL.
    state["expires"] = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    if rows:
        last = rows[-1][0]
        state["sequence"] = last.feed_sequence
        next_checkpoint = codec.next(state, {"id": last.id, "created_at": last.created_at})
    else:
        state["sequence"] = after_sequence
        next_checkpoint = codec.next(state, {"id": uuid.UUID(int=0), "created_at": datetime.now(UTC)})
    return {"items": events, "checkpoint": next_checkpoint, "has_more": has_more}
