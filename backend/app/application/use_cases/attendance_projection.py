"""Canonical attendance response data shared by HTTP and MCP projections."""

from dataclasses import asdict
from typing import Any

from app.application.use_cases.attendance_dashboard import (
    AttendanceGroupDashboardSummary,
    AttendanceMissingDashboardPage,
)


def attendance_summary_data(projection: AttendanceGroupDashboardSummary) -> dict[str, Any]:
    sessions = []
    for activity in projection.activities:
        row = asdict(activity)
        row["id"] = row.pop("session_id")
        sessions.append(row)
    return dict(
        group_id=projection.group_id,
        group_name=projection.group_name,
        revision=projection.revision,
        sessions=sessions,
    )


def attendance_missing_data(
    projection: AttendanceMissingDashboardPage, *, page_size: int
) -> dict[str, Any]:
    return dict(
        session_id=projection.session_id,
        revision=projection.revision,
        items=[asdict(item) for item in projection.page.items],
        has_more=projection.page.has_more,
        next_cursor=projection.page.next_cursor,
        page_size=page_size,
    )
