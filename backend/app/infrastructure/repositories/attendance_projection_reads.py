"""Bound actual attendance materialization queries before Python classification."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.value_objects.attendance_read_limits import (
    AttendanceReadLimitError,
    AttendanceReadLimits,
)


def bounded_attendance_text(column: Any, limit: int, limits: AttendanceReadLimits | None) -> Any:
    return func.substr(column, 1, limit + 1).label(column.key) if limits else column


async def load_attendance_rows(
    session: AsyncSession,
    statement: Select[Any],
    *,
    limits: AttendanceReadLimits | None,
    projection: tuple[Any, ...] = (),
    scalar: bool = False,
    activity_rows: bool = False,
    text_limits: tuple[tuple[str, int], ...] = (),
) -> list[Any]:
    maximum = (limits.activities if activity_rows else limits.source_rows) if limits else None
    if maximum is not None:
        if projection:
            statement = statement.with_only_columns(*projection, maintain_column_froms=True)
        statement = statement.limit(maximum + 1)
    result = await session.execute(statement)
    rows = list(result.scalars().all() if scalar and not limits else result.all())
    if maximum is not None and len(rows) > maximum:
        raise AttendanceReadLimitError()
    if limits:
        for row in rows:
            for field, limit in text_limits:
                value = getattr(row, field)
                if not isinstance(value, str) or len(value) > limit:
                    raise AttendanceReadLimitError()
    return rows
