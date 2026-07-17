"""Canonical normalization for reviewed and extracted passport fields."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.domain.exceptions.exceptions import ValidationError

PASSPORT_DATE_FIELDS = ("date_of_birth", "date_of_issue", "date_of_expiry")
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize_reviewed_passport_fields(fields: dict[str, str]) -> dict[str, str]:
    """Trim reviewed values and reject impossible passport dates."""

    normalized: dict[str, str] = {}
    for key, raw_value in fields.items():
        if not isinstance(key, str) or not isinstance(raw_value, str):
            raise ValidationError(
                "Reviewed passport fields must contain text values.",
                field="confirmed_fields",
            )
        value = " ".join(raw_value.strip().split())
        if not value:
            continue
        if key in PASSPORT_DATE_FIELDS:
            value = normalize_passport_date(value, field=key)
        normalized[key] = value

    _validate_date_order(normalized)
    return normalized


def normalize_extracted_passport_dates(fields: dict[str, Any]) -> dict[str, Any]:
    """Keep OCR dates only when they are valid, canonical, and mutually possible."""

    normalized = dict(fields)
    for field in PASSPORT_DATE_FIELDS:
        raw_value = normalized.get(field)
        if not isinstance(raw_value, str) or not raw_value.strip():
            normalized.pop(field, None)
            continue
        try:
            normalized[field] = normalize_passport_date(raw_value, field=field)
        except ValidationError:
            normalized.pop(field, None)

    try:
        _validate_date_order(
            {
                field: value
                for field in PASSPORT_DATE_FIELDS
                if isinstance((value := normalized.get(field)), str)
            }
        )
    except ValidationError as exc:
        # Date of issue is the non-MRZ visual field and therefore the least
        # authoritative when it conflicts with checksum-backed passport dates.
        if exc.field == "date_of_issue":
            normalized.pop("date_of_issue", None)
        else:
            normalized.pop(exc.field or "", None)
    return normalized


def normalize_passport_date(value: str, *, field: str) -> str:
    """Return a passport date in ISO YYYY-MM-DD format."""

    normalized = value.strip()
    if not _ISO_DATE_PATTERN.fullmatch(normalized):
        raise ValidationError(
            f"{_date_label(field)} must use YYYY-MM-DD format.",
            field=field,
        )
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValidationError(
            f"Enter a valid {_date_label(field).lower()}.",
            field=field,
        ) from exc

    today = date.today()
    if parsed.year < 1900 or parsed.year > 2200:
        raise ValidationError(
            f"Enter a valid {_date_label(field).lower()}.",
            field=field,
        )
    if field == "date_of_birth" and parsed >= today:
        raise ValidationError("Date of birth must be in the past.", field=field)
    if field == "date_of_issue" and parsed > today:
        raise ValidationError("Date of issue cannot be in the future.", field=field)
    return parsed.isoformat()


def _validate_date_order(fields: dict[str, str]) -> None:
    birth = _parsed(fields.get("date_of_birth"))
    issued = _parsed(fields.get("date_of_issue"))
    expiry = _parsed(fields.get("date_of_expiry"))

    if birth and issued and issued <= birth:
        raise ValidationError(
            "Date of issue must be after the date of birth.",
            field="date_of_issue",
        )
    if issued and expiry and expiry <= issued:
        raise ValidationError(
            "Date of issue must be before the date of expiry.",
            field="date_of_issue",
        )
    if birth and expiry and expiry <= birth:
        raise ValidationError(
            "Date of expiry must be after the date of birth.",
            field="date_of_expiry",
        )


def _parsed(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _date_label(field: str) -> str:
    return {
        "date_of_birth": "Date of birth",
        "date_of_issue": "Date of issue",
        "date_of_expiry": "Date of expiry",
    }.get(field, "Date")
