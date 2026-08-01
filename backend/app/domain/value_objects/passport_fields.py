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
    "place_of_issue",
    "date_of_birth",
    "date_of_issue",
    "date_of_expiry",
    "sex",
)
LEGACY_ISSUING_COUNTRY_FIELD = "issuing_country"
_ACCEPTED_REVIEWABLE_PASSPORT_FIELDS = (
    *REVIEWABLE_PASSPORT_FIELDS,
    LEGACY_ISSUING_COUNTRY_FIELD,
)
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_REVIEWED_FIELD_VALUE_LENGTH = 160
MAX_REVIEWED_FIELDS_TOTAL_LENGTH = 1_440
_PASSPORT_SEX_IDENTITIES = {
    "m": "M",
    "male": "M",
    "f": "F",
    "female": "F",
    "x": "X",
    "unspecified": "X",
    "<": "X",
}


def validate_reviewed_passport_payload(fields: dict[str, str]) -> None:
    """Bound and allowlist untrusted client review dictionaries."""

    unknown = sorted(set(fields) - set(_ACCEPTED_REVIEWABLE_PASSPORT_FIELDS))
    if unknown:
        raise ValidationError(
            "Unsupported reviewed passport field.",
            field="confirmed_fields",
        )
    if len(fields) > len(_ACCEPTED_REVIEWABLE_PASSPORT_FIELDS):
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
    canonical_fields = canonical_passport_fields(fields) or {}
    for key, raw_value in canonical_fields.items():
        if key == LEGACY_ISSUING_COUNTRY_FIELD:
            # Older clients may still submit this key during a staggered
            # deployment. Issuing country and the visibly printed place of
            # issue are different facts. Preserve the legacy fact under its
            # own key for audit compatibility, but never copy it into the new
            # canonical field.
            if not isinstance(raw_value, str):
                raise ValidationError(
                    "Reviewed passport fields must contain text values.",
                    field="confirmed_fields",
                )
            legacy_value = " ".join(raw_value.strip().split())
            if legacy_value:
                normalized[key] = legacy_value
            continue
        if not isinstance(key, str) or not isinstance(raw_value, str):
            raise ValidationError(
                "Reviewed passport fields must contain text values.",
                field="confirmed_fields",
            )
        value = " ".join(raw_value.strip().split())
        if not value:
            # An explicitly empty surname is meaningful: some passports have
            # no surname. Preserve that key so client and staff review can
            # clear a mistaken extraction; Gemini still verifies the visible
            # absence before AI approval.
            if key == "surname":
                normalized[key] = ""
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

    merged = canonical_passport_fields(confirmed_fields) or {}
    canonical_extracted = canonical_passport_fields(extracted_fields) or {}
    conflicts: list[dict[str, str | None]] = []
    for field in REVIEWABLE_PASSPORT_FIELDS:
        manual_value = _text_value(merged.get(field))
        extracted_value = _text_value(canonical_extracted.get(field))
        if field == "surname" and field in merged and not manual_value:
            # An explicit blank surname is a reviewed value, not an extraction
            # gap. Preserve it and surface any later non-empty extraction for
            # staff review instead of silently copying that value over it.
            if extracted_value:
                conflicts.append(
                    {
                        "field": field,
                        "manual_value": "",
                        "extracted_value": extracted_value,
                        "status": "mismatch",
                    }
                )
            continue
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


def canonical_passport_fields(
    fields: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a non-mutating passport-field view without semantic aliases.

    Historical JSON may contain ``issuing_country`` while new records contain
    ``place_of_issue``. Those values describe different passport facts. The
    legacy key is preserved for audit/read compatibility, but it must never be
    exposed, verified, or persisted as the canonical place-of-issue value.
    """

    if fields is None:
        return None
    return dict(fields)


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


def normalize_passport_sex_identity(value: str) -> str:
    """Return the canonical ICAO sex marker for a recognized source value.

    Unknown labels intentionally return an empty string so an importer cannot
    silently invent gender evidence. The original source value can remain in
    audit metadata for staff review.
    """

    if not isinstance(value, str):
        return ""
    normalized = " ".join(unicodedata.normalize("NFKC", value).strip().split()).casefold()
    return _PASSPORT_SEX_IDENTITIES.get(normalized, "")


def normalize_passport_number_identity(value: str) -> str:
    """Return the punctuation-insensitive canonical passport identity."""

    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value).upper()
    return re.sub(r"[^A-Z0-9]", "", normalized)


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
        return normalize_passport_number_identity(normalized)
    if field == "nationality":
        return canonical_country_identity(normalized)
    if field == "sex":
        key = normalized.casefold()
        return normalize_passport_sex_identity(normalized) or key
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
