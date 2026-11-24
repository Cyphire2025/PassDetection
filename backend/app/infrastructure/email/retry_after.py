"""Provider-neutral Retry-After parsing with a one-day upper bound."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def retry_after_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    if stripped.isascii() and stripped.isdigit():
        digits = stripped.lstrip("0") or "0"
        return 86_400 if len(digits) > 5 else min(int(digits), 86_400)
    try:
        parsed = parsedate_to_datetime(stripped)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delay = int((parsed - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None
    return min(max(delay, 0), 86_400)
