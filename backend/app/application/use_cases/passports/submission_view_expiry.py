"""Roster view expiry with explicit projection boundaries."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from .submission_view_fields import _display_name, _field_value, _normalized_tokens
from .submission_view_types import ExpiryAlert


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _expiry_alerts(
    submissions: list[Any],
    *,
    today: date,
    travel_date: date | None,
) -> tuple[ExpiryAlert, ...]:
    warning_date = _add_months(travel_date or today, 6)
    alerts: list[ExpiryAlert] = []
    for submission in submissions:
        expiry_text = _field_value(submission, "date_of_expiry")
        try:
            expiry = date.fromisoformat(expiry_text)
        except (TypeError, ValueError):
            continue
        is_expired = expiry < today
        if not is_expired and expiry > warning_date:
            continue
        alerts.append(
            ExpiryAlert(
                submission_id=submission.id,
                client_name=_display_name(submission),
                client_email=submission.client_email,
                passport_number=(_field_value(submission, "passport_number") or None),
                date_of_expiry=expiry.isoformat(),
                status="expired" if is_expired else "near_expiry",
            )
        )
    return tuple(
        sorted(
            alerts,
            key=lambda alert: (
                alert.date_of_expiry,
                _normalized_tokens(alert.client_name),
                str(alert.submission_id),
            ),
        )
    )
