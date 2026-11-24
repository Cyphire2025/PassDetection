"""Atomic readiness changes after the facade refreshes/fences its current actor."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.travel_tracker import TrackerMarkRequest, TrackerMarkResponse
from app.domain.entities.entities import User
from app.domain.exceptions.travel_tracker import TravelTrackerError
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.travel_tracker_model import TravelTrackerModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.travel_tracker.projections import counts
from app.infrastructure.travel_tracker.queries import (
    filter_roster,
    group_summary,
    load_group,
    roster,
)
from app.infrastructure.travel_tracker.spreadsheet_values import MAX_EXPORT_ROWS


async def mark_authorized(
    session: AsyncSession,
    user: User,
    allowed_group_ids: Sequence[uuid.UUID] | None,
    group_id: uuid.UUID,
    body: TrackerMarkRequest,
    *,
    commit: bool = True,
) -> TrackerMarkResponse:
    group = await load_group(session, user, allowed_group_ids, group_id, lock=True)
    statement = roster(group)
    requested_ids = list(dict.fromkeys(body.passenger_ids or []))
    if body.selection is not None:
        statement = filter_roster(
            statement, track=body.track, status=body.selection.status, search=body.selection.search
        )
    else:
        statement = statement.where(PassportSubmissionModel.id.in_(requested_ids))
    rows = (
        await session.execute(
            statement.order_by(PassportSubmissionModel.id)
            .limit(MAX_EXPORT_ROWS + 1)
            .with_for_update(of=PassportSubmissionModel)
            .execution_options(populate_existing=True)
        )
    ).all()
    if len(rows) > MAX_EXPORT_ROWS:
        raise TravelTrackerError(
            status_code=422, detail="Narrow the selection to at most 20,000 passengers."
        )
    if body.selection is not None and len(rows) != body.expected_count:
        raise TravelTrackerError(
            status_code=409,
            detail="The passenger selection changed. Refresh the list and try again.",
        )
    if body.selection is None and len(rows) != len(requested_ids):
        raise TravelTrackerError(
            status_code=404, detail="One or more selected passengers were not found in this group."
        )
    flag = "visa_applied" if body.track == "visa" else "flight_booked"
    now, changed = (datetime.now(UTC), [])
    for passenger, tracker in rows:
        if bool(tracker and getattr(tracker, flag)) == body.marked:
            continue
        if tracker is None:
            tracker = TravelTrackerModel(
                passenger_id=passenger.id,
                group_id=group.id,
                agency_id=group.agency_id,
                visa_applied=False,
                flight_booked=False,
            )
            session.add(tracker)
        setattr(tracker, flag, body.marked)
        setattr(tracker, body.track + "_updated_at", now)
        setattr(tracker, body.track + "_updated_by", user.id)
        changed.append(passenger.id)
    if changed:
        await AuditLogRepository(session).record(
            action="travel_tracker.marks_changed",
            entity_type="client_group",
            entity_id=str(group.id),
            agency_id=group.agency_id,
            user_id=user.id,
            actor_email=user.email,
            metadata={
                "track": body.track,
                "marked": body.marked,
                "updated_count": len(changed),
                "passenger_ids": [str(value) for value in changed],
            },
        )
    await session.flush()
    summary = (await group_summary(session, [group]))[group.id]
    result = TrackerMarkResponse(
        updated_count=len(changed),
        unchanged_count=len(rows) - len(changed),
        passenger_ids=[passenger.id for passenger, _ in rows],
        counts=counts(summary, body.track),
    )
    if commit:
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return result
