from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.application.use_cases.email_integrations.deadlines import resolve_deadline
from app.domain.value_objects.email_ai_analysis import (
    DeadlineCandidate,
    DeadlineResolutionStatus,
)


def _candidate(expression: str) -> DeadlineCandidate:
    return DeadlineCandidate(
        source_text=f"Please respond {expression}.",
        expression=expression,
        confidence=0.95,
    )


@pytest.mark.parametrize(
    ("expression", "expected_iso"),
    [
        ("2026-08-02", "2026-08-02T18:00:00+05:30"),
        ("2026-08-02 17:00", "2026-08-02T17:00:00+05:30"),
        ("2026-08-02T11:30:00Z", "2026-08-02T17:00:00+05:30"),
        ("today", "2026-07-30T18:00:00+05:30"),
        ("EOD", "2026-07-30T18:00:00+05:30"),
        ("tomorrow EOD", "2026-07-31T18:00:00+05:30"),
        ("kal shaam tak", "2026-07-31T18:00:00+05:30"),
        ("within 24 hours", "2026-07-31T13:30:00+05:30"),
        ("within 2 days", "2026-08-01T13:30:00+05:30"),
        ("Friday", "2026-07-31T18:00:00+05:30"),
    ],
)
def test_supported_deadlines_resolve_deterministically(
    expression: str,
    expected_iso: str,
) -> None:
    result = resolve_deadline(
        _candidate(expression),
        reference_time=datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
        timezone_name="Asia/Kolkata",
    )

    assert result.status == DeadlineResolutionStatus.RESOLVED
    assert result.due_at is not None
    assert result.due_at.isoformat() == expected_iso


def test_named_weekday_equal_to_reference_day_requires_review() -> None:
    result = resolve_deadline(
        _candidate("Thursday"),
        reference_time=datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
        timezone_name="Asia/Kolkata",
    )

    assert result.status == DeadlineResolutionStatus.REVIEW_REQUIRED
    assert result.due_at is None
    assert result.reason_code == "ambiguous_same_day_weekday"

    next_result = resolve_deadline(
        _candidate("next Thursday"),
        reference_time=datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
        timezone_name="Asia/Kolkata",
    )
    assert next_result.status == DeadlineResolutionStatus.RESOLVED
    assert next_result.due_at is not None
    assert next_result.due_at.date().isoformat() == "2026-08-06"


@pytest.mark.parametrize(
    "expression",
    ["2026-07-29", "2026-07-30T07:59:00Z"],
)
def test_explicit_dates_before_the_message_require_review(
    expression: str,
) -> None:
    result = resolve_deadline(
        _candidate(expression),
        reference_time=datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
        timezone_name="Asia/Kolkata",
    )

    assert result.status == DeadlineResolutionStatus.REVIEW_REQUIRED
    assert result.due_at is None
    assert result.reason_code == "explicit_deadline_before_message"


@pytest.mark.parametrize(
    ("expression", "timezone_name", "reason_code"),
    [
        ("Friday or Monday", "Asia/Kolkata", "ambiguous_multiple_expressions"),
        ("very soon", "Asia/Kolkata", "unsupported_or_ambiguous_expression"),
        ("within 999 hours", "Asia/Kolkata", "relative_deadline_out_of_range"),
        ("tomorrow", "Not/A-Timezone", "invalid_timezone"),
        ("2026-11-01 01:30", "America/New_York", "ambiguous_or_invalid_local_time"),
    ],
)
def test_ambiguous_or_invalid_deadlines_fail_to_review(
    expression: str,
    timezone_name: str,
    reason_code: str,
) -> None:
    result = resolve_deadline(
        _candidate(expression),
        reference_time=datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
        timezone_name=timezone_name,
    )

    assert result.status == DeadlineResolutionStatus.REVIEW_REQUIRED
    assert result.due_at is None
    assert result.reason_code == reason_code
