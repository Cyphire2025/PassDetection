"""Shared SQL status normalization and count semantics for stored activities."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, func, or_

ACTIVE_STATUSES = frozenset({"queued", "processing"})
SUCCESS_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})
UNCERTAIN_STATUSES = frozenset({"delivery_unknown", "stalled"})
KNOWN_STATUSES = ACTIVE_STATUSES | SUCCESS_STATUSES | UNCERTAIN_STATUSES
ACTIVITY_STALE_AFTER = timedelta(minutes=30)
ACTIVITY_STATUS_COUNT_KEYS = (
    "queued", "processing", "submitted", "sent", "delivered", "read",
    "failed", "delivery_unknown", "stalled",
)


def _normalized_activity_status(
    status_column: Any,
    status_updated_column: Any,
    *,
    stale_cutoff: datetime,
) -> Any:
    return case(
        (
            and_(status_column.in_(ACTIVE_STATUSES), status_updated_column < stale_cutoff),
            "stalled",
        ),
        else_=status_column,
    )


def _status_aggregates(
    status_column: Any,
    status_updated_column: Any,
    *,
    stale_cutoff: datetime,
) -> tuple[Any, ...]:
    is_active = status_column.in_(ACTIVE_STATUSES)
    is_stale = and_(is_active, status_updated_column < stale_cutoff)
    is_queued = and_(is_active, ~is_stale)
    is_unknown = or_(status_column.in_(UNCERTAIN_STATUSES), is_stale)
    is_failed = ~status_column.in_(KNOWN_STATUSES)
    normalized_status = _normalized_activity_status(
        status_column, status_updated_column, stale_cutoff=stale_cutoff,
    )
    return (
        func.count().label("total"),
        func.count().filter(is_queued).label("queued"),
        func.count().filter(status_column.in_(SUCCESS_STATUSES)).label("sent"),
        func.count().filter(is_failed).label("failed"),
        func.count().filter(is_unknown).label("delivery_unknown"),
        *(
            func.count()
            .filter(is_failed if name == "failed" else normalized_status == name)
            .label(f"status_count_{name}")
            for name in ACTIVITY_STATUS_COUNT_KEYS
        ),
    )


def _failed_status_predicate(status_column: Any) -> Any:
    return ~status_column.in_(KNOWN_STATUSES)
