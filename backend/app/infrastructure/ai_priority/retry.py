"""Bounded, standards-aware Retry-After handling for Gemini requests."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


def parse_retry_after_ms(
    value: str | None,
    *,
    now: datetime | None = None,
) -> int | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        seconds = float(normalized)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(normalized)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        current = now or datetime.now(tz=UTC)
        seconds = (retry_at - current).total_seconds()
    if not math.isfinite(seconds):
        return None
    if seconds < 0:
        return 0
    return min(300_000, int(seconds * 1_000))


def retry_after_delay_seconds(
    value: str | None,
    *,
    remaining_seconds: float,
    attempt_number: int = 1,
    jitter_unit: float = 0.5,
    base_delay_seconds: float = 0.25,
    max_delay_seconds: float = 2.0,
) -> float | None:
    """Return Retry-After or bounded exponential backoff with jitter.

    ``jitter_unit`` is injected by callers so tests can be deterministic.  A
    value from 0 through 1 scales the exponential delay from 75% through 125%.
    """

    retry_after_ms = parse_retry_after_ms(value)
    if retry_after_ms is not None:
        delay_seconds = retry_after_ms / 1_000
    else:
        exponent = max(0, attempt_number - 1)
        exponential = base_delay_seconds * (2**exponent)
        bounded_jitter = min(1.0, max(0.0, jitter_unit))
        delay_seconds = min(
            max_delay_seconds,
            exponential * (0.75 + (0.5 * bounded_jitter)),
        )
    if delay_seconds + 0.05 >= remaining_seconds:
        return None
    return delay_seconds
