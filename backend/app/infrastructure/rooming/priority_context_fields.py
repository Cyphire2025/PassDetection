"""Imported grouping descriptors and deterministic priority-field selection."""

from __future__ import annotations

from app.infrastructure.database.models import WhatsAppBroadcastRecipientModel

from .priority_field_policy import (
    MAX_ROOMING_FIELD_KEY_LENGTH,
    _is_unavailable_priority,
    normalize_imported_field_key,
)


def imported_priority_fields(
    recipients: list[WhatsAppBroadcastRecipientModel],
) -> list[dict[str, str]]:
    imported_labels: dict[str, str] = {}
    for recipient in recipients:
        for raw_key in recipient.imported_fields or {}:
            normalized = normalize_imported_field_key(raw_key)
            field_key = f"whatsapp:{normalized}"
            if (
                not normalized
                or _is_unavailable_priority(raw_key)
                or len(field_key) > MAX_ROOMING_FIELD_KEY_LENGTH
            ):
                continue
            imported_labels.setdefault(normalized, str(raw_key))
    return [
        {"key": f"whatsapp:{normalized}", "label": label, "source": "whatsapp"}
        for normalized, label in sorted(
            imported_labels.items(), key=lambda item: (item[1].casefold(), item[0])
        )
    ]


def selected_priority_fields(
    fields: list[dict[str, str]],
    required_fields: list[dict[str, str]] | None,
    requested_keys: list[str] | None,
) -> dict[str, dict[str, str]]:
    """Required descriptors retain their original key precedence and order."""
    return {
        field["key"]: field
        for field in [*fields, *(required_fields or [])]
        if requested_keys is None or field["key"] in requested_keys
    }
