"""Deterministic server-side passport information-page classification gates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ACCEPTED_PASSPORT_DOCUMENT_STATUSES = frozenset({"verified", "enhanced"})


def is_accepted_passport_information_page(value: object) -> bool:
    """Return true only for a positive, structured server-side classification."""

    if not isinstance(value, Mapping):
        return False
    status = value.get("status")
    available = value.get("available")
    return (
        isinstance(status, str)
        and status in ACCEPTED_PASSPORT_DOCUMENT_STATUSES
        and available is True
    )


def passport_document_classification(
    extracted_fields: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    """Read the bounded classification object from extracted fields."""

    if not isinstance(extracted_fields, Mapping):
        return None
    raw = extracted_fields.get("ai_verification")
    return raw if isinstance(raw, Mapping) else None
