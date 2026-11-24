"""Exact roster heading/value normalization, independent of document parsing."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from typing import TypeVar

from app.application.use_cases.whatsapp.contact_normalization import (
    clean_whatsapp_name,
    normalize_whatsapp_phone,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _MATCH_DATE_FIELD_KEYS,
    _MATCH_FIELD_KEY_ALIASES,
    _MATCH_IDENTIFIER_FIELD_KEYS,
    _MISSING_MATCH_VALUES,
)

_MappingValue = TypeVar("_MappingValue")


_NormalizedInput = TypeVar("_NormalizedInput")


def _normalized_key(value: object) -> str:
    text = str(value or "").strip().casefold()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text)).strip("_")


def normalize_matching_field_key(value: object) -> str:
    """Return the stable key used to join an imported heading to an answer.

    The import layer already stores snake-case keys. Keeping this normalizer in
    the matcher also supports older/manual payloads and common aliases such as
    ``DOB`` versus the passport field ``date_of_birth``.
    """

    normalized = _normalized_key(value)
    return _MATCH_FIELD_KEY_ALIASES.get(normalized, normalized)


def _normalized_name(value: object) -> str | None:
    cleaned = clean_whatsapp_name(value)
    if not cleaned:
        return None
    compatible = unicodedata.normalize("NFKC", cleaned).casefold()
    normalized = "".join(
        character if character.isalnum() else " " for character in compatible
    ).strip()
    return " ".join(normalized.split()) or None


def _normalized_email(value: object) -> str | None:
    text = str(value or "").strip().casefold()
    if not text or "@" not in text:
        return None
    local, separator, domain = text.partition("@")
    if not separator or not local or "." not in domain:
        return None
    return f"{local}@{domain}"


def _normalized_identifier(value: object) -> str | None:
    normalized = re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())
    return normalized or None


def _normalized_date(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = " ".join(str(value or "").strip().split())
    if not text:
        return None
    iso_candidate = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_candidate).date().isoformat()
    except ValueError:
        pass
    for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return _normalized_identifier(text)


def _normalized_generic(value: object) -> str | None:
    compatible = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = "".join(character if character.isalnum() else " " for character in compatible)
    normalized = " ".join(normalized.split())
    if normalized in _MISSING_MATCH_VALUES:
        return None
    return normalized


def _normalized_phone(value: object) -> str | None:
    return normalize_whatsapp_phone(None if value is None else str(value))


def _selected_field_normalizer(field_key: str) -> Callable[[object], str | None]:
    canonical = normalize_matching_field_key(field_key)
    if canonical == "phone_number":
        return _normalized_phone
    if canonical == "email":
        return _normalized_email
    if canonical == "name":
        return _normalized_name
    if canonical in _MATCH_DATE_FIELD_KEYS or "date_of_birth" in canonical:
        return _normalized_date
    if (
        canonical in _MATCH_IDENTIFIER_FIELD_KEYS
        or canonical.endswith("_code")
        or canonical.endswith("_id")
    ):
        return _normalized_identifier
    return _normalized_generic


def _mapping_values(
    mapping: Mapping[str, _MappingValue],
    keys: frozenset[str],
) -> list[_MappingValue]:
    values: list[_MappingValue] = []
    for raw_key, value in mapping.items():
        normalized = _normalized_key(raw_key)
        base_key = re.sub(r"_\d+$", "", normalized)
        if normalized in keys or base_key in keys:
            values.append(value)
    return values


def _mapping_field_values(
    mapping: Mapping[str, _MappingValue],
    field_key: str,
) -> list[_MappingValue]:
    selected_key = _normalized_key(field_key)
    values: list[_MappingValue] = []
    # Alternate ``_2`` keys are created only when the importer records the
    # base key here. Legitimate headings such as ``terminal_2`` stay distinct.
    conflicting = {
        key for item in str(mapping.get("duplicate_conflicting_fields", "")).split(",")
        if (key := _normalized_key(item))
    }
    for raw_key, value in mapping.items():
        normalized = _normalized_key(raw_key)
        base_key = re.sub(r"_\d+$", "", normalized)
        if base_key not in conflicting:
            base_key = normalized
        if normalized == selected_key or base_key == selected_key:
            values.append(value)
    return values


def _normalized_values(
    values: Iterable[_NormalizedInput],
    normalizer: Callable[[_NormalizedInput], str | None],
) -> frozenset[str]:
    normalized: set[str] = set()
    for value in values:
        # Placeholder cells must never become strong exact-match tokens such
        # as ``NA`` or ``NOTAVAILABLE`` under identifier/date normalizers.
        if _normalized_generic(value) is None:
            continue
        item = normalizer(value)
        if item:
            normalized.add(item)
    return frozenset(normalized)
