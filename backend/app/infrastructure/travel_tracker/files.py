"""Authorized tracker export/import orchestration using owned native workers."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.travel_tracker import TrackerImportPreview, TrackerStatus, TrackerTrack
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import ImageValidationError
from app.domain.exceptions.travel_tracker import TravelTrackerError
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.sensitive_read_audit import record_sensitive_read
from app.infrastructure.security.upload_validator import malware_scanner_from_settings
from app.infrastructure.travel_tracker.queries import (
    filter_roster,
    load_group,
    roster,
    validate_filters,
)
from app.infrastructure.travel_tracker.spreadsheets import (
    MAX_EXPORT_ROWS,
    MAX_UPLOAD_BYTES,
    TrackerSpreadsheetError,
    build_export,
    match_rows,
    read_rows,
)
from app.infrastructure.travel_tracker.threading import run_tracker_work


async def export(
    session: AsyncSession,
    user: User,
    allowed_group_ids: Sequence[uuid.UUID] | None,
    group_id: uuid.UUID,
    *,
    track: TrackerTrack = "visa",
    status: TrackerStatus = "all",
    search: str | None = None,
) -> tuple[bytes, str]:
    group = await load_group(session, user, allowed_group_ids, group_id)
    statement = filter_roster(roster(group), track=track, status=status, search=search)
    rows = (
        await session.execute(
            statement.order_by(
                func.lower(PassportSubmissionModel.client_name), PassportSubmissionModel.id
            ).limit(MAX_EXPORT_ROWS + 1)
        )
    ).all()
    if len(rows) > MAX_EXPORT_ROWS:
        raise TravelTrackerError(
            status_code=422, detail="Narrow the export to at most 20,000 passengers."
        )
    try:
        content = await run_tracker_work(
            build_export, group, [(passenger, tracker) for passenger, tracker in rows]
        )
    except TrackerSpreadsheetError as exc:
        raise TravelTrackerError(status_code=422, detail=str(exc)) from exc
    await AuditLogRepository(session).record(
        action="travel_tracker.exported",
        entity_type="client_group",
        entity_id=str(group.id),
        agency_id=group.agency_id,
        user_id=user.id,
        metadata={"track": track, "status": status, "exported_count": len(rows)},
    )
    filename = re.sub("[^A-Za-z0-9._-]+", "-", group.name).strip("-.")[:80] or "group"
    return (content, f"{filename}-{track}-{status}.xlsx")


async def preview(
    session: AsyncSession,
    user: User,
    allowed_group_ids: Sequence[uuid.UUID] | None,
    group_id: uuid.UUID,
    *,
    content: bytes,
    filename: str,
    track: TrackerTrack = "visa",
    marked: bool = True,
) -> TrackerImportPreview:
    validate_filters(track, "all", None)
    group = await load_group(session, user, allowed_group_ids, group_id)
    if len(content) > MAX_UPLOAD_BYTES:
        raise TravelTrackerError(status_code=413, detail="Upload a file smaller than 8 MB.")
    try:
        await run_tracker_work(malware_scanner_from_settings().scan, content)
        records = await run_tracker_work(read_rows, content, filename)
    except (TrackerSpreadsheetError, ImageValidationError) as exc:
        raise TravelTrackerError(status_code=422, detail=str(exc)) from exc
    rows = (await session.execute(roster(group).limit(MAX_EXPORT_ROWS + 1))).all()
    if len(rows) > MAX_EXPORT_ROWS:
        raise TravelTrackerError(
            status_code=422, detail="Spreadsheet matching supports groups up to 20,000 passengers."
        )
    result = await run_tracker_work(
        match_rows, records, [passenger for passenger, _ in rows], track=track, marked=marked
    )
    await record_sensitive_read(
        session,
        user=user,
        kind="group_view",
        agency_id=group.agency_id,
        entity_id=group.id,
        count=len(rows),
    )
    return result
