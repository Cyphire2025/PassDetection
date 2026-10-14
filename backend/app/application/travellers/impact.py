"""Bounded document-change impact without mutating frozen trip snapshots.

Each page scans at most 100 indexed person participations, creates reference-only
review tasks and advances a durable cursor atomically. Memory is O(page_size).
External ticket/visa/manifest systems are not integrated; the task tells an
operator to review downstream outputs linked to the frozen source submission.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.document_selection import current_document_id
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerChangeEventModel,
    TravellerDocumentReviewTaskModel,
    TravellerParticipationModel,
    TravellerPassportModel,
)

IMPACT_EVENT_TYPES = ("document_promoted", "document_blocked")


async def process_impact_page(session: AsyncSession, event_id: uuid.UUID, *, page_size: int = 100) -> int:
    if not 1 <= page_size <= 100:
        raise ValueError("Impact page size must be between 1 and 100")
    event = await session.scalar(select(TravellerChangeEventModel).where(
        TravellerChangeEventModel.id == event_id,
    ).with_for_update().execution_options(populate_existing=True))
    if event is None or event.processed_at is not None:
        return 0
    if event.event_type not in IMPACT_EVENT_TYPES or event.traveller_id is None:
        event.processed_at = datetime.now(UTC)
        return 0
    replacement = await session.scalar(select(current_document_id(TravellerPassportModel)).where(
        TravellerPassportModel.agency_id == event.agency_id,
        TravellerPassportModel.company_id == event.company_id,
        TravellerPassportModel.traveller_id == event.traveller_id,
        TravellerPassportModel.is_default.is_(True), TravellerPassportModel.status == "accepted",
    ).limit(1))
    query = select(TravellerParticipationModel, ClientGroupModel.status, ClientGroupModel.deleted_at,
        ClientGroupModel.company_id).join(ClientGroupModel,
        (ClientGroupModel.id == TravellerParticipationModel.group_id)
        & (ClientGroupModel.agency_id == TravellerParticipationModel.agency_id),
    ).where(TravellerParticipationModel.agency_id == event.agency_id,
        TravellerParticipationModel.company_id == event.company_id,
        TravellerParticipationModel.traveller_id == event.traveller_id,
    )
    if event.event_type == "document_promoted" and replacement is None:
        event.processed_at = datetime.now(UTC)
        return 0
    if event.impact_cursor is not None:
        query = query.where(TravellerParticipationModel.id > event.impact_cursor)
    scanned = (await session.execute(query.order_by(TravellerParticipationModel.id).limit(page_size))).all()
    rows = [row for row, status, deleted_at, company_id in scanned
        if status == "active" and deleted_at is None and company_id == event.company_id
        and row.status in {"submitted", "accepted"} and row.document_revision_id is not None
        and (row.passport_id == event.aggregate_id if event.event_type == "document_blocked"
             else row.document_revision_id != replacement)]
    existing = set((await session.scalars(select(TravellerDocumentReviewTaskModel.participation_id).where(
        TravellerDocumentReviewTaskModel.event_id == event.id,
        TravellerDocumentReviewTaskModel.participation_id.in_([row.id for row in rows]),
    ))).all()) if rows else set()
    for row in rows:
        if row.id not in existing:
            session.add(TravellerDocumentReviewTaskModel(agency_id=event.agency_id, company_id=event.company_id,
                event_id=event.id, participation_id=row.id, old_document_revision_id=row.document_revision_id,
                new_document_revision_id=replacement, expected_participation_revision=row.revision,
                reason_code="document_blocked" if event.event_type == "document_blocked" else "document_changed"))
    if scanned:
        event.impact_cursor = scanned[-1][0].id
    event.impact_attempt_count = 0
    event.impact_error_code = None
    event.impact_available_at = datetime.now(UTC)
    if len(scanned) < page_size:
        event.processed_at = datetime.now(UTC)
    await session.flush()
    return len(scanned)
