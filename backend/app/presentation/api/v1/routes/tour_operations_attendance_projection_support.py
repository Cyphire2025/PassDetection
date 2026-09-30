"""Attendance closeout and dashboard presentation helpers.

Keep transport-only projections and the shared close transition out of the
tour-operations router so that route handlers remain focused on authorization,
scope resolution, and application-service orchestration.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.attendance_dashboard import (
    AttendanceGroupDashboardSummary,
    AttendanceMissingDashboardPage,
)
from app.application.use_cases.attendance_projection import (
    attendance_missing_data,
    attendance_summary_data,
)
from app.infrastructure.database.models import AttendanceSessionModel
from app.infrastructure.repositories.attendance_closeout_repository import (
    AttendanceCloseoutCounts,
    AttendanceCloseoutStatus,
)
from app.presentation.api.v1.schemas.attendance_closeout_schemas import (
    AttendanceCloseoutCheckpointRequest,
    AttendanceCloseoutStatusResponse,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AttendanceMissingPassengersPageResponse,
    GroupAttendanceSummaryResponse,
)


def attendance_closeout_counts(
    body: AttendanceCloseoutCheckpointRequest,
) -> AttendanceCloseoutCounts:
    return AttendanceCloseoutCounts(
        pending_count=body.pending_count,
        sending_count=body.sending_count,
        retryable_count=body.retryable_count,
        needs_review_count=body.needs_review_count,
        unreviewed_rejected_count=body.unreviewed_rejected_count,
        oldest_pending_age_seconds=body.oldest_pending_age_seconds,
    )


def attendance_activity_valid_after(
    attendance_session: AttendanceSessionModel,
) -> datetime:
    return attendance_session.started_at or attendance_session.created_at


def attendance_closeout_status_response(
    closeout: AttendanceCloseoutStatus,
) -> AttendanceCloseoutStatusResponse:
    return AttendanceCloseoutStatusResponse.model_validate(closeout)


def require_attendance_closeout_clearance(
    closeout: AttendanceCloseoutStatusResponse,
    *,
    exception_reason: str | None,
) -> bool:
    if closeout.ready:
        return False
    if exception_reason is not None:
        return True
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "ATTENDANCE_CLOSEOUT_BLOCKED",
            "message": (
                "Every assigned coordinator must publish a recent zero-queue "
                "checkpoint before this activity can close."
            ),
            "closeout": closeout.model_dump(mode="json"),
        },
    )


def attendance_closeout_audit_metadata(
    closeout: AttendanceCloseoutStatusResponse,
    *,
    exception_used: bool,
    exception_reason: str | None,
) -> dict[str, object]:
    return {
        "exception_used": exception_used,
        "exception_reason": exception_reason if exception_used else None,
        "checkpoint_ttl_seconds": closeout.checkpoint_ttl_seconds,
        "active_assignment_count": closeout.active_assignment_count,
        "ready_assignment_count": closeout.ready_assignment_count,
        "missing_assignment_count": closeout.missing_assignment_count,
        "stale_assignment_count": closeout.stale_assignment_count,
        "nonzero_assignment_count": closeout.nonzero_assignment_count,
        "blocked_assignment_count": closeout.blocked_assignment_count,
        "unresolved_count": closeout.unresolved_count,
        "oldest_pending_age_seconds": closeout.oldest_pending_age_seconds,
        "coordinators": [
            {
                "coordinator_id": str(item.coordinator_id),
                "runtime_id": str(item.runtime_id) if item.runtime_id else None,
                "runtime_kind": item.runtime_kind,
                "runtime_status": item.runtime_status,
                "state": item.state,
                "reported_at": item.reported_at.isoformat() if item.reported_at else None,
                "pending_count": item.pending_count,
                "sending_count": item.sending_count,
                "retryable_count": item.retryable_count,
                "needs_review_count": item.needs_review_count,
                "unreviewed_rejected_count": item.unreviewed_rejected_count,
                "oldest_pending_age_seconds": item.oldest_pending_age_seconds,
            }
            for item in closeout.coordinators
        ],
    }


async def close_shared_attendance_activity(
    session: AsyncSession,
    attendance_session: AttendanceSessionModel,
) -> bool:
    """Apply the only supported global attendance close transition.

    Callers must authorize and lock the canonical activity before entering this
    shared mutation boundary. Completed activities remain scannable so queued
    offline events can reconcile after an authorized close.
    """

    if attendance_session.status == "completed":
        return False
    if attendance_session.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an active attendance activity can be closed",
        )
    now = datetime.now(tz=UTC)
    attendance_session.status = "completed"
    attendance_session.completed_at = now
    attendance_session.updated_at = now
    await session.flush()
    return True


def etag_matches(if_none_match: str | None, current_etag: str) -> bool:
    if not if_none_match:
        return False
    expected = current_etag.removeprefix("W/")
    return any(
        candidate.strip().removeprefix("W/") in {"*", expected}
        for candidate in if_none_match.split(",")
    )


def attendance_summary_cache_headers(revision: str) -> tuple[str, dict[str, str]]:
    etag = f'"{revision}"'
    return etag, {
        "ETag": etag,
        "Cache-Control": "private, no-cache",
        "Vary": "Cookie, Authorization",
    }


def attendance_summary_response(
    projection: AttendanceGroupDashboardSummary,
) -> GroupAttendanceSummaryResponse:
    return GroupAttendanceSummaryResponse(**attendance_summary_data(projection))


def attendance_missing_passengers_response(
    projection: AttendanceMissingDashboardPage,
    *,
    page_size: int,
) -> AttendanceMissingPassengersPageResponse:
    return AttendanceMissingPassengersPageResponse(**attendance_missing_data(projection, page_size=page_size))


def attendance_snapshot_changed_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": "ATTENDANCE_SNAPSHOT_CHANGED",
                "message": (
                    "Attendance changed while this page was loading. "
                    "Refresh the activity before continuing."
                ),
            }
        },
        headers={"Cache-Control": "private, no-store"},
    )
