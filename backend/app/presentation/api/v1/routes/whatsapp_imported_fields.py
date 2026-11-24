"""Bounded imported metadata and selectable matching-field catalogs."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from fastapi import HTTPException, status

from app.presentation.api.v1.routes.whatsapp_contact_values import (
    _EMPTY_EXCEL_VALUES,
    _MATCHING_FIELD_LABELS,
    MAX_WHATSAPP_IMPORTED_FIELD_VALUE_LENGTH,
    MAX_WHATSAPP_IMPORTED_FIELDS,
    MAX_WHATSAPP_IMPORTED_FIELDS_BYTES,
    WHATSAPP_NON_MATCHING_IMPORTED_FIELDS,
    WHATSAPP_ROSTER_SOURCE_FIELDS,
    _clean_name,
    _excel_cell_text,
    _excel_field_key,
    _excel_header_label,
    _normalize_phone,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppMatchingFieldOption,
    WhatsAppRecipientInput,
    WhatsAppRejectedContactInput,
)


def _safe_imported_fields(value: Any) -> dict[str, str]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient imported fields must be a key/value object",
        )

    cleaned: dict[str, str] = {}
    imported_field_count = 0
    total_size = 0
    for raw_key, raw_value in value.items():
        key = _excel_field_key(raw_key)
        text_value = _excel_cell_text(raw_value)
        if not key or not text_value or _excel_header_label(text_value) in _EMPTY_EXCEL_VALUES:
            continue
        if key == "name":
            text_value = _clean_name(text_value) or ""
        elif key == "phone_number":
            text_value = _normalize_phone(text_value) or text_value
        elif key == "email":
            text_value = text_value.casefold()
        elif key == "passport_number":
            text_value = re.sub(
                r"[^A-Z0-9]+",
                "",
                text_value.upper(),
            )
        elif key in {"agent_code", "staff_code"}:
            # These are imported reference values, not identifiers used for
            # authentication. Preserve meaningful separators for staff review.
            text_value = " ".join(text_value.upper().split())
        else:
            text_value = " ".join(text_value.split())
        if not text_value:
            continue
        is_roster_source_field = key in WHATSAPP_ROSTER_SOURCE_FIELDS
        if (
            not is_roster_source_field
            and imported_field_count >= MAX_WHATSAPP_IMPORTED_FIELDS
            and key not in cleaned
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Each WhatsApp recipient can contain at most "
                    f"{MAX_WHATSAPP_IMPORTED_FIELDS} imported fields"
                ),
            )
        text_value = text_value[:MAX_WHATSAPP_IMPORTED_FIELD_VALUE_LENGTH]
        if key in cleaned:
            continue
        total_size += len(key.encode("utf-8")) + len(text_value.encode("utf-8"))
        if total_size > MAX_WHATSAPP_IMPORTED_FIELDS_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A WhatsApp recipient's imported fields are too large",
            )
        cleaned[key] = text_value
        if not is_roster_source_field:
            imported_field_count += 1
    return cleaned


def _matching_field_label(key: str) -> str:
    return _MATCHING_FIELD_LABELS.get(
        key,
        " ".join(part.capitalize() for part in key.split("_") if part),
    )


def _merge_imported_field_keys(
    existing: Any = None,
    *,
    declared_keys: Iterable[object] = (),
    imported_fields: Iterable[Mapping[str, object]] = (),
) -> list[str]:
    """Return a bounded, stable union of selectable imported field keys."""

    ordered: list[str] = []
    seen: set[str] = set()

    def include(key: str) -> None:
        if (
            key
            and key not in WHATSAPP_NON_MATCHING_IMPORTED_FIELDS
            and len(ordered) < MAX_WHATSAPP_IMPORTED_FIELDS
            and key not in seen
        ):
            seen.add(key)
            ordered.append(key)

    for raw_key in existing if isinstance(existing, list) else []:
        include(_excel_field_key(raw_key))
    for raw_key in declared_keys:
        include(_excel_field_key(raw_key))
    for fields in imported_fields:
        conflicting = {
            _excel_field_key(value)
            for value in str(fields.get("duplicate_conflicting_fields", "")).split(",")
            if _excel_field_key(value)
        }
        for raw_key in fields:
            key = _excel_field_key(raw_key)
            generated_base = re.sub(r"_\d+$", "", key)
            if generated_base != key and generated_base in conflicting:
                continue
            include(key)
    return ordered


def _matching_field_options(keys: Any) -> list[WhatsAppMatchingFieldOption]:
    return [
        WhatsAppMatchingFieldOption(key=key, label=_matching_field_label(key))
        for key in _merge_imported_field_keys(keys)
    ]


def _imported_field_keys_for_contacts(
    existing: Any = None,
    *,
    declared_keys: Iterable[object] = (),
    contacts: Iterable[WhatsAppRecipientInput | WhatsAppRejectedContactInput] = (),
) -> list[str]:
    """Preserve headings from the workbook and all accepted/rejected input rows."""
    return _merge_imported_field_keys(
        existing,
        declared_keys=declared_keys,
        imported_fields=(contact.imported_fields for contact in contacts),
    )


def _parse_imported_field_keys(value: str | None) -> list[str]:
    """Parse the header catalog carried from a prior workbook preview."""

    try:
        raw_keys = json.loads(value or "[]")
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid imported Excel heading list",
        ) from exc
    if not isinstance(raw_keys, list) or any(not isinstance(raw_key, str) for raw_key in raw_keys):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Imported Excel headings must be a list of text keys",
        )
    if len(raw_keys) > MAX_WHATSAPP_IMPORTED_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"An Excel import can expose at most {MAX_WHATSAPP_IMPORTED_FIELDS} headings"),
        )
    return _merge_imported_field_keys(declared_keys=raw_keys)
