"""Canonical normalization for reviewed and extracted passport fields."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

from app.domain.exceptions.exceptions import ValidationError

PASSPORT_DATE_FIELDS = ("date_of_birth", "date_of_issue", "date_of_expiry")
REVIEWABLE_PASSPORT_FIELDS = (
    "surname",
    "given_names",
    "passport_number",
    "nationality",
    "issuing_country",
    "date_of_birth",
    "date_of_issue",
    "date_of_expiry",
    "sex",
)
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_REVIEWED_FIELD_VALUE_LENGTH = 160
MAX_REVIEWED_FIELDS_TOTAL_LENGTH = 1_440


def validate_reviewed_passport_payload(fields: dict[str, str]) -> None:
    """Bound and allowlist untrusted client review dictionaries."""

    unknown = sorted(set(fields) - set(REVIEWABLE_PASSPORT_FIELDS))
    if unknown:
        raise ValidationError(
            "Unsupported reviewed passport field.",
            field="confirmed_fields",
        )
    if len(fields) > len(REVIEWABLE_PASSPORT_FIELDS):
        raise ValidationError(
            "Too many reviewed passport fields were supplied.",
            field="confirmed_fields",
        )

    total_length = 0
    for key, value in fields.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValidationError(
                "Reviewed passport fields must contain text values.",
                field="confirmed_fields",
            )
        if len(value) > MAX_REVIEWED_FIELD_VALUE_LENGTH:
            raise ValidationError(
                "A reviewed passport field is too long.",
                field=key,
            )
        total_length += len(key) + len(value)
    if total_length > MAX_REVIEWED_FIELDS_TOTAL_LENGTH:
        raise ValidationError(
            "Reviewed passport fields are too large.",
            field="confirmed_fields",
        )


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


def reconcile_confirmed_with_extraction(
    confirmed_fields: dict[str, Any] | None,
    extracted_fields: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, str | None]]]:
    """Fill confirmed blanks and surface non-destructive verification conflicts."""

    if confirmed_fields is None:
        return None, []

    merged = dict(confirmed_fields)
    conflicts: list[dict[str, str | None]] = []
    for field in REVIEWABLE_PASSPORT_FIELDS:
        manual_value = _text_value(merged.get(field))
        extracted_value = _text_value(extracted_fields.get(field))
        if not manual_value:
            if extracted_value:
                merged[field] = extracted_value
            continue
        if not extracted_value:
            conflicts.append(
                {
                    "field": field,
                    "manual_value": manual_value,
                    "extracted_value": None,
                    "status": "not_extracted",
                }
            )
            continue
        if _comparable_passport_value(field, manual_value) != _comparable_passport_value(
            field,
            extracted_value,
        ):
            conflicts.append(
                {
                    "field": field,
                    "manual_value": manual_value,
                    "extracted_value": extracted_value,
                    "status": "mismatch",
                }
            )
    return merged, conflicts


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


def _text_value(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _comparable_passport_value(field: str, value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).strip().split())
    if field == "passport_number":
        return re.sub(r"[^A-Z0-9]", "", normalized.upper())
    if field in {"nationality", "issuing_country"}:
        return canonical_country_identity(normalized)
    if field == "sex":
        key = normalized.casefold()
        return {
            "m": "M",
            "male": "M",
            "f": "F",
            "female": "F",
            "x": "X",
            "unspecified": "X",
            "<": "X",
        }.get(key, key)
    return normalized.casefold()


def canonical_country_identity(value: str) -> str:
    """Return a conservative alpha-3 identity for an accepted country label."""

    key = re.sub(r"[^A-Z]", "", value.upper())
    aliases = {
        # The traveller UI historically stores the nationality display label
        # while passports and Gemini commonly return the ISO alpha-3 code.
        "INDIAN": "IND",
    }
    if key in aliases:
        return aliases[key]
    # pycountry is a runtime dependency, but retaining the India fallback keeps
    # domain-only unit tests usable in minimal host Python environments.
    try:
        import pycountry
    except ImportError:
        return {"IND": "IND", "INDIA": "IND", **aliases}.get(key, key)
    try:
        country = pycountry.countries.lookup(value)
    except LookupError:
        return {"IND": "IND", "INDIA": "IND", **aliases}.get(key, key)
    return str(country.alpha_3).upper()
