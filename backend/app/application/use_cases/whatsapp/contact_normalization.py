"""Canonical normalization shared by WhatsApp import and comparison flows."""

from __future__ import annotations

import re
from typing import Any

from app.domain.value_objects.phone_number import (
    PHONE_ALLOWED_RE as PHONE_ALLOWED_RE,
)
from app.domain.value_objects.phone_number import normalize_phone_number

# Keep the long-standing import path available to sending and matching code.
normalize_whatsapp_phone = normalize_phone_number


def clean_whatsapp_name(value: Any) -> str | None:
    """Collapse whitespace and apply the import field length bound."""

    if value is None:
        return None
    name = re.sub(r"\s+", " ", str(value)).strip()
    return name[:255] or None
