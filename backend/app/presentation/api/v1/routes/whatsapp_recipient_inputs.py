"""Input validation, duplicate merging and durable recipient reactivation."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    MAX_WHATSAPP_IMPORTED_FIELD_VALUE_LENGTH,
    MAX_WHATSAPP_IMPORTED_FIELDS,
    MAX_WHATSAPP_IMPORTED_FIELDS_BYTES,
    WHATSAPP_NON_MATCHING_IMPORTED_FIELDS,
    WHATSAPP_ROSTER_SOURCE_FIELDS,
    _clean_name,
    _normalize_phone,
)
from app.presentation.api.v1.routes.whatsapp_imported_fields import _safe_imported_fields
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppRecipientInput,
    WhatsAppSupportContactInput,
)


def _merge_recipient_inputs(
    existing: WhatsAppRecipientInput,
    incoming: WhatsAppRecipientInput,
) -> WhatsAppRecipientInput:
    # Delivery remains one phone record. Full individual rows live in rejected
    # source records, so never append an unbounded name_3/name_4/... family.
    # Preserve the first row's identity fields; retain one alternate for the
    # existing preview UI. O(fields) work/space, independent of duplicate count.
    merged_fields = dict(existing.imported_fields)
    conflicting_keys = set(merged_fields.pop("duplicate_conflicting_fields", "").split(", ")) - {""}
    total_size = sum(
        len(key.encode()) + len(value.encode()) for key, value in merged_fields.items()
    )
    field_count = len(merged_fields.keys() - WHATSAPP_ROSTER_SOURCE_FIELDS)

    def add_if_fits(key: str, value: str) -> None:
        nonlocal total_size, field_count
        size = len(key.encode()) + len(value.encode())
        if (
            key not in merged_fields
            and field_count < MAX_WHATSAPP_IMPORTED_FIELDS
            and total_size + size <= MAX_WHATSAPP_IMPORTED_FIELDS_BYTES
        ):
            merged_fields[key] = value
            total_size += size
            field_count += 1

    for key, value in incoming.imported_fields.items():
        if key in WHATSAPP_NON_MATCHING_IMPORTED_FIELDS:
            continue
        current = merged_fields.get(key)
        if current is not None and current.casefold() != value.casefold():
            conflicting_keys.add(key)
            add_if_fits(f"{key[:62]}_2", value)
    if conflicting_keys:
        add_if_fits(
            "duplicate_conflicting_fields",
            ", ".join(sorted(conflicting_keys))[:MAX_WHATSAPP_IMPORTED_FIELD_VALUE_LENGTH],
        )
    return WhatsAppRecipientInput(
        name=existing.name or incoming.name,
        phone_number=existing.phone_number,
        imported_fields=_safe_imported_fields(merged_fields),
    )


def _parse_manual_contacts(value: str) -> list[WhatsAppRecipientInput]:
    try:
        parsed = json.loads(value or "[]")
        if not isinstance(parsed, list):
            raise TypeError
        return [WhatsAppRecipientInput(**item) for item in parsed]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid manual contact list",
        ) from exc


def _normalized_recipient_inputs(
    contacts: list[WhatsAppRecipientInput],
) -> dict[str, WhatsAppRecipientInput]:
    normalized_contacts: dict[str, WhatsAppRecipientInput] = {}
    invalid_numbers: list[str] = []
    for contact in contacts:
        normalized = _normalize_phone(contact.phone_number)
        if not normalized:
            invalid_numbers.append(contact.phone_number)
            continue
        sanitized = WhatsAppRecipientInput(
            name=contact.name,
            phone_number=contact.phone_number,
            imported_fields=_safe_imported_fields(contact.imported_fields),
        )
        existing = normalized_contacts.get(normalized)
        normalized_contacts[normalized] = (
            _merge_recipient_inputs(existing, sanitized) if existing else sanitized
        )
    if invalid_numbers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{len(invalid_numbers)} WhatsApp number(s) are invalid. "
                "Use 8 to 15 digits with an optional country code."
            ),
        )
    if not normalized_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one valid WhatsApp number",
        )
    unnamed_numbers = [
        contact.phone_number
        for contact in normalized_contacts.values()
        if not _clean_name(contact.name)
    ]
    if unnamed_numbers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Every recipient needs a name for personalised messages. "
                f"Missing names for {len(unnamed_numbers)} contact(s)."
            ),
        )
    if any(len(_clean_name(contact.name) or "") > 100 for contact in normalized_contacts.values()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient names must be 100 characters or fewer",
        )
    return normalized_contacts


def _activate_recipient_models(
    *,
    session: AsyncSession,
    group: WhatsAppBroadcastGroupModel,
    existing_by_phone: dict[str, WhatsAppBroadcastRecipientModel],
    normalized_contacts: dict[str, WhatsAppRecipientInput],
    now: datetime,
    display_orders_by_phone: dict[str, int] | None = None,
) -> None:
    """Reactivate matching rows so their durable message checklist survives."""

    display_orders_by_phone = display_orders_by_phone or {}
    for normalized, contact in normalized_contacts.items():
        existing = existing_by_phone.get(normalized)
        if existing:
            if existing.suppressed_by_roster_resolution_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "A recipient in this import is currently marked as "
                        "replaced in a linked passport group. Restore that "
                        "replacement from the group before adding them back."
                    ),
                )
            existing.name = _clean_name(contact.name)
            existing.phone_number = contact.phone_number.strip()
            if contact.imported_fields:
                existing.imported_fields = contact.imported_fields
            existing.removed_at = None
            existing.merged_into_recipient_id = None
            continue
        session.add(
            WhatsAppBroadcastRecipientModel(
                broadcast_group_id=group.id,
                agency_id=group.agency_id,
                name=_clean_name(contact.name),
                phone_number=contact.phone_number.strip(),
                normalized_phone_number=normalized,
                imported_fields=contact.imported_fields,
                display_order=display_orders_by_phone.get(normalized),
                removed_at=None,
                created_at=now,
            )
        )


def _parse_support_contacts(value: str) -> list[WhatsAppSupportContactInput]:
    try:
        parsed = json.loads(value or "[]")
        if not isinstance(parsed, list):
            raise TypeError
        contacts = [WhatsAppSupportContactInput(**item) for item in parsed]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid customer support contact list",
        ) from exc
    if not contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one customer support contact",
        )
    normalized: dict[str, WhatsAppSupportContactInput] = {}
    for contact in contacts:
        phone = _normalize_phone(contact.phone_number)
        if not phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid WhatsApp number for support contact {contact.name}",
            )
        normalized.setdefault(phone, contact)
    if len(normalized) > 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add no more than three customer support contacts",
        )
    return list(normalized.values())
