"""Explicit spreadsheet contact sources for broadcasts, never OTP authority."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.domain.value_objects.client_collection_provenance import (
    CLIENT_COLLECTION_SUBMITTED_KEY,
    CLIENT_COLLECTION_SUBMITTED_VALUE,
)


def imported_phone_column_priority(key: object) -> int | None:
    """Recognize current and legacy exported contact headers, including duplicates."""
    compact = re.sub(r"[^a-z0-9]", "", str(key).casefold())
    duplicate_suffix = r"(?:[2-9]|[1-9][0-9]+)?"
    if re.fullmatch(r"verifiedwhatsappnumbers?" + duplicate_suffix, compact):
        return 0
    if re.fullmatch(r"uploadphone" + duplicate_suffix, compact):
        return 1
    return None


def explicit_imported_broadcast_phone(metadata: Mapping[str, Any]) -> tuple[str | None, bool]:
    """Prefer Verified WhatsApp over legacy Upload Phone; never skip an invalid winner."""
    columns = [
        (priority, value)
        for key, value in metadata.items()
        if (priority := imported_phone_column_priority(key)) is not None
    ]
    if not columns:
        return None, False
    priority = min(item[0] for item in columns)
    values = {
        str(value).strip()
        for rank, value in columns
        if rank == priority and str(value or "").strip()
    }
    if not values:
        return None, False
    normalized = {normalize_whatsapp_phone(value) for value in values}
    if len(normalized) != 1 or None in normalized:
        return None, True
    return normalized.pop(), True


def raw_explicit_imported_broadcast_phone(metadata: Mapping[str, Any]) -> tuple[str, bool]:
    """Return the winning source value for an editor, including invalid/cleared data."""
    columns = [
        (priority, str(value or "").strip())
        for key, value in metadata.items()
        if (priority := imported_phone_column_priority(key)) is not None
    ]
    if not columns:
        return "", False
    priority = min(rank for rank, _ in columns)
    return "; ".join(dict.fromkeys(
        value for rank, value in columns if rank == priority and value
    )), True


def has_public_collection_contact(submission: Any) -> bool:
    """Retain public contact authority even when its current value was removed."""
    metadata = getattr(submission, "staff_metadata", None) or {}
    if metadata.get(CLIENT_COLLECTION_SUBMITTED_KEY) == CLIENT_COLLECTION_SUBMITTED_VALUE:
        return True
    confidence = getattr(submission, "confidence_score", None) or {}
    known_import = confidence.get("source") == "excel_import" or str(
        getattr(submission, "image_s3_key", "") or ""
    ).startswith("excel-imports/")
    return getattr(submission, "client_reviewed_at", None) is not None and not known_import
