"""Per-group atomic privacy-safe browser discard synchronization."""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.repositories.attendance_discard_repository import AttendanceDiscardInput
from app.infrastructure.repositories.attendance_runtime_repository import AttendanceRuntimeError
from app.presentation.api.v1.routes.attendance_runtime_dependencies import (
    DiscardSynchronizationDependencies,
)
from app.presentation.api.v1.schemas.attendance_runtime_schemas import (
    AttendanceDiscardBatchRequest,
    AttendanceDiscardBatchResponse,
    AttendanceDiscardItemRequest,
    AttendanceDiscardItemResponse,
)


async def synchronize_browser_discard_groups(
    body: AttendanceDiscardBatchRequest,
    request: Request,
    current_user: User,
    session: AsyncSession,
    *,
    dependencies: DiscardSynchronizationDependencies,
) -> AttendanceDiscardBatchResponse:
    settings = dependencies.settings
    agency_id = dependencies.agency_id
    runtime = await dependencies.resolve_runtime(
        request,
        session=session,
        agency_id=agency_id,
        coordinator_user_id=current_user.id,
        required=True,
    )
    if runtime is None:  # pragma: no cover - required=True is exhaustive
        raise RuntimeError("Attendance runtime resolution was incomplete")

    grouped: dict[tuple[uuid.UUID, uuid.UUID], list[AttendanceDiscardItemRequest]] = defaultdict(
        list
    )
    for item in body.items:
        grouped[(item.group_id, item.session_id)].append(item)

    responses: dict[uuid.UUID, AttendanceDiscardItemResponse] = {}
    accepted_count = 0
    already_applied_count = 0
    rejected_count = 0
    for (group_id, session_id), items in grouped.items():
        try:
            await dependencies.ensure_group(
                session,
                agency_id,
                group_id,
                current_user.id,
            )
            attendance_session = await dependencies.get_session(
                session,
                agency_id,
                session_id,
                current_user.id,
            )
            if attendance_session.group_id != group_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            # A replay conflict can be detected after fresh IDs were inserted.
            # Keep the entire rejected group reversible while other groups in
            # this request retain their independently acknowledged evidence.
            async with session.begin_nested():
                results = await dependencies.discard_repository(session).record_batch(
                    agency_id=agency_id,
                    group_id=group_id,
                    session_id=attendance_session.id,
                    coordinator_user_id=current_user.id,
                    runtime_registration_id=runtime.id,
                    items=tuple(
                        AttendanceDiscardInput(
                            discard_event_id=item.discard_event_id,
                            scan_reference=item.scan_reference,
                            reason_category=item.reason_category,
                            captured_at=item.captured_at,
                            discarded_at=item.discarded_at,
                        )
                        for item in items
                    ),
                    retention_days=settings.attendance_discard_retention_days,
                )
        except (HTTPException, AttendanceRuntimeError, ValueError):
            for item in items:
                responses[item.discard_event_id] = AttendanceDiscardItemResponse(
                    discard_event_id=item.discard_event_id,
                    status="rejected",
                    reason_code="DISCARD_SCOPE_NOT_AUTHORIZED",
                )
                rejected_count += 1
            continue
        for result in results:
            responses[result.discard_event_id] = AttendanceDiscardItemResponse(
                discard_event_id=result.discard_event_id,
                status=result.status,
                received_at=result.received_at,
            )
            if result.status == "accepted":
                accepted_count += 1
            else:
                already_applied_count += 1

    await dependencies.audit_repository(session).record(
        action="attendance.discard_evidence_synchronized",
        entity_type="attendance_runtime",
        agency_id=agency_id,
        user_id=current_user.id,
        entity_id=str(runtime.id),
        result="blocked" if rejected_count and not accepted_count else "success",
        metadata={
            "accepted_count": accepted_count,
            "already_applied_count": already_applied_count,
            "rejected_count": rejected_count,
            "runtime_kind": runtime.runtime_kind,
            "reason_categories": sorted({item.reason_category for item in body.items}),
        },
    )
    return AttendanceDiscardBatchResponse(
        items=[responses[item.discard_event_id] for item in body.items]
    )
