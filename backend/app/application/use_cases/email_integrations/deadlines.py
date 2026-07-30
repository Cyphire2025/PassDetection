"""Deterministic resolution of bounded email deadline expressions."""

from __future__ import annotations

import re
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.value_objects.email_ai_analysis import (
    DeadlineCandidate,
    DeadlineResolutionStatus,
    ResolvedDeadline,
)

_ISO_EXPRESSION = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(?:(?:T| )[0-2]\d:[0-5]\d(?::[0-5]\d)?(?:Z|[+-][0-2]\d:[0-5]\d)?)?$",
    re.IGNORECASE,
)
_WITHIN_EXPRESSION = re.compile(
    r"^(?:within|in)\s+(?P<count>\d{1,3})\s+(?P<unit>hours?|days?)$",
    re.IGNORECASE,
)
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_WEEKDAY_EXPRESSION = re.compile(
    r"^(?:by\s+)?(?P<next>next\s+)?"
    r"(?P<weekday>monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"(?:\s+(?:eod|end\s+of\s+day))?$",
    re.IGNORECASE,
)
_DEADLINE_WORD = re.compile(
    r"\b(?:today|tomorrow|eod|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)


def resolve_deadline(
    candidate: DeadlineCandidate,
    *,
    reference_time: datetime,
    timezone_name: str,
    end_of_day_hour: int = 18,
) -> ResolvedDeadline:
    """Resolve supported expressions or return an explicit review requirement.

    No locale guessing is performed. Bare weekdays mean the nearest future
    occurrence; a bare weekday equal to the reference weekday is deliberately
    treated as ambiguous.
    """

    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        return _review(candidate, "reference_time_missing_offset")
    if not 0 <= end_of_day_hour <= 23:
        return _review(candidate, "invalid_end_of_day_hour")
    try:
        timezone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return _review(candidate, "invalid_timezone")

    local_reference = reference_time.astimezone(timezone)
    expression = _normalize_expression(candidate.expression)
    if not expression:
        return _review(candidate, "empty_expression")

    if _ISO_EXPRESSION.fullmatch(expression):
        return _resolve_iso(
            candidate,
            expression=expression,
            timezone=timezone,
            end_of_day_hour=end_of_day_hour,
            reference_time=reference_time,
        )

    if expression in {"today", "today eod", "eod", "end of day"}:
        due_at = _local_end_of_day(local_reference, day_offset=0, hour=end_of_day_hour)
        return _resolved(candidate, due_at, "relative_today")

    if expression in {
        "tomorrow",
        "tomorrow eod",
        "tomorrow evening",
        "kal shaam",
        "kal shaam tak",
    }:
        due_at = _local_end_of_day(local_reference, day_offset=1, hour=end_of_day_hour)
        return _resolved(
            candidate,
            due_at,
            (
                "relative_tomorrow_evening"
                if expression in {"tomorrow evening", "kal shaam", "kal shaam tak"}
                else "relative_tomorrow"
            ),
        )

    within_match = _WITHIN_EXPRESSION.fullmatch(expression)
    if within_match is not None:
        count = int(within_match.group("count"))
        unit = within_match.group("unit").casefold()
        if count < 1:
            return _review(candidate, "invalid_relative_count")
        if unit.startswith("hour"):
            if count > 720:
                return _review(candidate, "relative_deadline_out_of_range")
            return _resolved(
                candidate,
                (reference_time.astimezone(UTC) + timedelta(hours=count)).astimezone(timezone),
                "relative_hours",
            )
        if count > 365:
            return _review(candidate, "relative_deadline_out_of_range")
        return _resolved(
            candidate,
            (reference_time.astimezone(UTC) + timedelta(days=count)).astimezone(timezone),
            "relative_days",
        )

    weekday_match = _WEEKDAY_EXPRESSION.fullmatch(expression)
    if weekday_match is not None:
        target_weekday = _WEEKDAYS[weekday_match.group("weekday").casefold()]
        day_delta = (target_weekday - local_reference.weekday()) % 7
        explicit_next = weekday_match.group("next") is not None
        if day_delta == 0 and not explicit_next:
            return _review(candidate, "ambiguous_same_day_weekday")
        if day_delta == 0:
            day_delta = 7
        due_at = _local_end_of_day(
            local_reference,
            day_offset=day_delta,
            hour=end_of_day_hour,
        )
        return _resolved(
            candidate,
            due_at,
            "named_weekday_next" if explicit_next else "named_weekday",
        )

    if len(_DEADLINE_WORD.findall(expression)) > 1 and not _is_single_iso_datetime(expression):
        return _review(candidate, "ambiguous_multiple_expressions")

    return _review(candidate, "unsupported_or_ambiguous_expression")


def _resolve_iso(
    candidate: DeadlineCandidate,
    *,
    expression: str,
    timezone: ZoneInfo,
    end_of_day_hour: int,
    reference_time: datetime,
) -> ResolvedDeadline:
    try:
        if len(expression) == 10:
            parsed_date = datetime.strptime(expression, "%Y-%m-%d").date()
            naive = datetime.combine(parsed_date, time(hour=end_of_day_hour))
            localized = _localize_unambiguous(naive, timezone)
            if localized is None:
                return _review(candidate, "ambiguous_or_invalid_local_time")
            return _resolved_iso_if_future(
                candidate,
                localized,
                reference_time=reference_time,
                reason_code="explicit_iso_date",
            )

        parsed = datetime.fromisoformat(expression.replace("z", "+00:00"))
    except ValueError:
        return _review(candidate, "invalid_iso_deadline")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        localized = _localize_unambiguous(parsed, timezone)
        if localized is None:
            return _review(candidate, "ambiguous_or_invalid_local_time")
        return _resolved_iso_if_future(
            candidate,
            localized,
            reference_time=reference_time,
            reason_code="explicit_iso_local_datetime",
        )
    return _resolved_iso_if_future(
        candidate,
        parsed.astimezone(timezone),
        reference_time=reference_time,
        reason_code="explicit_iso_datetime",
    )


def _resolved_iso_if_future(
    candidate: DeadlineCandidate,
    due_at: datetime,
    *,
    reference_time: datetime,
    reason_code: str,
) -> ResolvedDeadline:
    if due_at.astimezone(UTC) <= reference_time.astimezone(UTC):
        return _review(candidate, "explicit_deadline_before_message")
    return _resolved(candidate, due_at, reason_code)


def _localize_unambiguous(value: datetime, timezone: ZoneInfo) -> datetime | None:
    first = value.replace(tzinfo=timezone, fold=0)
    second = value.replace(tzinfo=timezone, fold=1)
    first_valid = first.astimezone(UTC).astimezone(timezone).replace(tzinfo=None) == value
    second_valid = second.astimezone(UTC).astimezone(timezone).replace(tzinfo=None) == value
    if not first_valid and not second_valid:
        return None
    if first_valid and second_valid and first.utcoffset() != second.utcoffset():
        return None
    return first if first_valid else second


def _local_end_of_day(reference: datetime, *, day_offset: int, hour: int) -> datetime:
    target_date = (reference + timedelta(days=day_offset)).date()
    return datetime.combine(target_date, time(hour=hour), tzinfo=reference.tzinfo)


def _normalize_expression(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().casefold())
    normalized = re.sub(r"^(?:due|deadline)\s+(?:by|on|is)?\s*", "", normalized)
    normalized = normalized.removeprefix("by ").strip()
    return normalized


def _is_single_iso_datetime(value: str) -> bool:
    return _ISO_EXPRESSION.fullmatch(value) is not None


def _resolved(
    candidate: DeadlineCandidate,
    due_at: datetime,
    reason_code: str,
) -> ResolvedDeadline:
    return ResolvedDeadline(
        source_text=candidate.source_text,
        expression=candidate.expression,
        confidence=candidate.confidence,
        status=DeadlineResolutionStatus.RESOLVED,
        due_at=due_at,
        reason_code=reason_code,
    )


def _review(candidate: DeadlineCandidate, reason_code: str) -> ResolvedDeadline:
    return ResolvedDeadline(
        source_text=candidate.source_text,
        expression=candidate.expression,
        confidence=candidate.confidence,
        status=DeadlineResolutionStatus.REVIEW_REQUIRED,
        due_at=None,
        reason_code=reason_code,
    )
