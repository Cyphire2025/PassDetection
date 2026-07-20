"""Canonical normalization shared by WhatsApp import and comparison flows."""

from __future__ import annotations

import re
from typing import Any

PHONE_ALLOWED_RE = re.compile(r"^(?:\+|00)?[\d\s().-]+$")


def normalize_whatsapp_phone(raw: str | None) -> str | None:
    """Return the exact E.164-like form accepted by WhatsApp imports."""

    value = (raw or "").strip()
    if not value or len(value) > 64 or not PHONE_ALLOWED_RE.fullmatch(value):
        return None
    has_plus = value.startswith("+")
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    if value.startswith("00"):
        digits = digits[2:]
    if not 8 <= len(digits) <= 15:
        return None
    if has_plus or value.startswith("00") or len(digits) > 10:
        if digits.startswith("0"):
            return None
        return f"+{digits}"
    if len(digits) == 10:
        return f"+91{digits}"
    return None


def clean_whatsapp_name(value: Any) -> str | None:
    """Collapse whitespace and apply the import field length bound."""

    if value is None:
        return None
    name = re.sub(r"\s+", " ", str(value)).strip()
    return name[:255] or None
