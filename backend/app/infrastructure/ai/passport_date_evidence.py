"""Normalize date evidence returned by passport vision providers."""

from __future__ import annotations

import re
from datetime import date
from typing import Final, Literal

_DATE_FIELDS: Final[frozenset[str]] = frozenset(
    {"date_of_birth", "date_of_issue", "date_of_expiry"}
)
_MONTHS: Final[dict[str, int]] = {
    "JAN": 1,
    "JANUARY": 1,
    "FEB": 2,
    "FEBRUARY": 2,
    "MAR": 3,
    "MARCH": 3,
    "APR": 4,
    "APRIL": 4,
    "MAY": 5,
    "JUN": 6,
    "JUNE": 6,
    "JUL": 7,
    "JULY": 7,
    "AUG": 8,
    "AUGUST": 8,
    "SEP": 9,
    "SEPT": 9,
    "SEPTEMBER": 9,
    "OCT": 10,
    "OCTOBER": 10,
    "NOV": 11,
    "NOVEMBER": 11,
    "DEC": 12,
    "DECEMBER": 12,
}
_MAX_DATE_EVIDENCE_CHARACTERS: Final[int] = 64
_TEXT_SEPARATOR: Final[str] = r"(?:\s*[-./,]\s*|\s+)"
_MONTH_TOKEN: Final[str] = r"([A-Z]{3,9})\.?"
PassportNumericDateOrder = Literal["day_first", "month_first"]


def normalize_passport_date_evidence(
    value: str,
    *,
    field: str,
    numeric_order: PassportNumericDateOrder | None = None,
) -> str:
    """Return one unambiguous ISO date from printed/provider date formats."""

    candidates = passport_date_evidence_candidates(value, field=field)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) == 2 and numeric_order is not None:
        return candidates[0] if numeric_order == "day_first" else candidates[1]
    return ""


def passport_numeric_date_order_hint(
    value: str,
) -> PassportNumericDateOrder | None:
    """Infer a document's numeric order only when one component exceeds 12."""

    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().upper().split())
    if not normalized or len(normalized) > _MAX_DATE_EVIDENCE_CHARACTERS:
        return None
    parts = _year_last_numeric_parts(normalized)
    if parts is None and re.fullmatch(r"[0-9]{8}", normalized):
        if 1900 <= int(normalized[:4]) <= 2200:
            return None
        parts = (int(normalized[:2]), int(normalized[2:4]), int(normalized[4:]))
    if parts is None:
        return None
    first, second, _year = parts
    if first > 12 and 1 <= second <= 12:
        return "day_first"
    if second > 12 and 1 <= first <= 12:
        return "month_first"
    return None


def passport_date_evidence_candidates(
    value: str,
    *,
    field: str,
) -> tuple[str, ...]:
    """Return bounded, plausible ISO interpretations for passport date text."""

    if field not in _DATE_FIELDS or not isinstance(value, str):
        return ()
    normalized = " ".join(value.strip().upper().split())
    if not normalized or len(normalized) > _MAX_DATE_EVIDENCE_CHARACTERS:
        return ()

    candidates: list[str] = []

    year_first = re.fullmatch(
        r"([0-9]{4})\s*([-./])\s*([0-9]{1,2})\s*\2\s*([0-9]{1,2})",
        normalized,
    ) or re.fullmatch(
        r"([0-9]{4})\s+([0-9]{1,2})\s+([0-9]{1,2})",
        normalized,
    )
    if year_first:
        if len(year_first.groups()) == 4:
            year, month, day = (
                int(year_first.group(1)),
                int(year_first.group(3)),
                int(year_first.group(4)),
            )
        else:
            year, month, day = map(int, year_first.groups())
        _append_candidate(
            candidates,
            field=field,
            year=year,
            month=month,
            day=day,
        )
        return tuple(candidates)

    day_or_month_first = _year_last_numeric_parts(normalized)
    if day_or_month_first:
        first, second, year = day_or_month_first
        _append_candidate(
            candidates,
            field=field,
            year=year,
            month=second,
            day=first,
        )
        if first != second:
            _append_candidate(
                candidates,
                field=field,
                year=year,
                month=first,
                day=second,
            )
        return tuple(candidates)

    if re.fullmatch(r"[0-9]{8}", normalized):
        if 1900 <= int(normalized[:4]) <= 2200:
            _append_candidate(
                candidates,
                field=field,
                year=int(normalized[:4]),
                month=int(normalized[4:6]),
                day=int(normalized[6:8]),
            )
        else:
            year = int(normalized[4:8])
            _append_candidate(
                candidates,
                field=field,
                year=year,
                month=int(normalized[2:4]),
                day=int(normalized[:2]),
            )
            _append_candidate(
                candidates,
                field=field,
                year=year,
                month=int(normalized[:2]),
                day=int(normalized[2:4]),
            )
        return tuple(candidates)

    day_named = re.fullmatch(
        rf"([0-9]{{1,2}})(?:ST|ND|RD|TH)?{_TEXT_SEPARATOR}"
        rf"{_MONTH_TOKEN}{_TEXT_SEPARATOR}([0-9]{{4}})",
        normalized,
    )
    if day_named:
        _append_named_candidate(
            candidates,
            field=field,
            year=int(day_named.group(3)),
            month_name=day_named.group(2),
            day=int(day_named.group(1)),
        )
        return tuple(candidates)

    month_named = re.fullmatch(
        rf"{_MONTH_TOKEN}{_TEXT_SEPARATOR}([0-9]{{1,2}})"
        rf"(?:ST|ND|RD|TH)?(?:,\s*|\s+)([0-9]{{4}})",
        normalized,
    )
    if month_named:
        _append_named_candidate(
            candidates,
            field=field,
            year=int(month_named.group(3)),
            month_name=month_named.group(1),
            day=int(month_named.group(2)),
        )
        return tuple(candidates)

    year_named = re.fullmatch(
        rf"([0-9]{{4}}){_TEXT_SEPARATOR}{_MONTH_TOKEN}"
        rf"{_TEXT_SEPARATOR}([0-9]{{1,2}})",
        normalized,
    )
    if year_named:
        _append_named_candidate(
            candidates,
            field=field,
            year=int(year_named.group(1)),
            month_name=year_named.group(2),
            day=int(year_named.group(3)),
        )
        return tuple(candidates)

    compact_named = re.fullmatch(r"([0-9]{1,2})([A-Z]{3,9})([0-9]{4})", normalized)
    if compact_named:
        _append_named_candidate(
            candidates,
            field=field,
            year=int(compact_named.group(3)),
            month_name=compact_named.group(2),
            day=int(compact_named.group(1)),
        )
        return tuple(candidates)

    compact_year_named = re.fullmatch(
        r"([0-9]{4})([A-Z]{3,9})([0-9]{1,2})",
        normalized,
    )
    if compact_year_named:
        _append_named_candidate(
            candidates,
            field=field,
            year=int(compact_year_named.group(1)),
            month_name=compact_year_named.group(2),
            day=int(compact_year_named.group(3)),
        )
    return tuple(candidates)


def _year_last_numeric_parts(value: str) -> tuple[int, int, int] | None:
    separated = re.fullmatch(
        r"([0-9]{1,2})\s*([-./])\s*([0-9]{1,2})\s*\2\s*([0-9]{4})",
        value,
    )
    if separated:
        return (
            int(separated.group(1)),
            int(separated.group(3)),
            int(separated.group(4)),
        )
    spaced = re.fullmatch(
        r"([0-9]{1,2})\s+([0-9]{1,2})\s+([0-9]{4})",
        value,
    )
    if spaced is None:
        return None
    return (
        int(spaced.group(1)),
        int(spaced.group(2)),
        int(spaced.group(3)),
    )


def _append_named_candidate(
    candidates: list[str],
    *,
    field: str,
    year: int,
    month_name: str,
    day: int,
) -> None:
    month = _MONTHS.get(month_name.rstrip("."))
    if month is not None:
        _append_candidate(
            candidates,
            field=field,
            year=year,
            month=month,
            day=day,
        )


def _append_candidate(
    candidates: list[str],
    *,
    field: str,
    year: int,
    month: int,
    day: int,
) -> None:
    try:
        parsed = date(year, month, day)
    except ValueError:
        return
    today = date.today()
    if parsed.year < 1900 or parsed.year > 2200:
        return
    if field == "date_of_birth" and parsed >= today:
        return
    if field == "date_of_issue" and parsed > today:
        return
    iso = parsed.isoformat()
    if iso not in candidates:
        candidates.append(iso)
