"""Canonical phone representation shared by collection and delivery workflows."""

from __future__ import annotations

import re

PHONE_ALLOWED_RE = re.compile(r"^(?:\+|00)?[0-9\s().-]+$")


def normalize_phone_number(raw: str | None) -> str | None:
    """Normalize supported numbers; bare ten-digit numbers use India's +91 code.

    This intentionally matches the existing WhatsApp import contract, rather
    than pretending to validate whether a number is assigned or reachable.
    """

    value = (raw or "").strip()
    if not value or len(value) > 64 or not PHONE_ALLOWED_RE.fullmatch(value):
        return None
    explicit_country_code = value.startswith(("+", "00"))
    digits = re.sub(r"\D", "", value)
    if value.startswith("00"):
        digits = digits[2:]
    if not 8 <= len(digits) <= 15:
        return None
    if explicit_country_code or len(digits) > 10:
        if digits.startswith("0"):
            return None
        return f"+{digits}"
    if len(digits) == 10:
        return f"+91{digits}"
    return None


def phone_numbers_equal(first: str | None, second: str | None) -> bool:
    """Compare legacy formatting without treating an invalid number as absent."""

    if not first or not first.strip():
        return not second or not second.strip()
    normalized = normalize_phone_number(first)
    return normalized is not None and normalized == normalize_phone_number(second)


def phone_storage_variants(raw: str) -> frozenset[str]:
    """Read compatibility for formats persisted by earlier public submissions."""

    normalized = normalize_phone_number(raw)
    if normalized is None:
        return frozenset({raw})
    digits = normalized[1:]
    values = {raw, normalized, digits, f"00{digits}"}
    if normalized.startswith("+91") and len(digits) == 12:
        values.add(digits[2:])
    return frozenset(values)
