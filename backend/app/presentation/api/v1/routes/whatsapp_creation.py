"""Shared validated, flush-only new broadcast creation; no existing roster mutation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.recipient_capacity import (
    MAX_WHATSAPP_RECIPIENTS,
    WhatsAppRecipientCapacityExceeded,
    require_whatsapp_recipient_capacity,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSupportContactModel,
)
from app.presentation.api.v1.routes.whatsapp_contact_support import (
    _add_rejected_contact_models,
    _clean_name,
    _clean_required_name,
    _imported_field_keys_for_contacts,
    _new_roster_display_orders,
    _normalize_phone,
    _normalized_recipient_inputs,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppRecipientInput,
    WhatsAppRejectedContactInput,
    WhatsAppSupportContactInput,
)


def validate_new_broadcast(
    *,
    name: str,
    organizing_company_name: str | None,
    contacts: list[WhatsAppRecipientInput],
    rejected_contacts: list[WhatsAppRejectedContactInput],
    support_contacts: list[WhatsAppSupportContactInput],
    recipient_opt_in_confirmed: bool,
) -> tuple[str, str, dict[str, WhatsAppRecipientInput], dict[str, WhatsAppSupportContactInput]]:
    """Pure validation is also used before the website acquires actor locks."""
    group_name = name.strip()
    if not group_name:
        raise HTTPException(400, "Group name is required")
    if len(group_name) > 100:
        raise HTTPException(400, "Group name must be 100 characters or fewer")
    company_name = _clean_name(organizing_company_name) or ""
    if len(company_name) > 100:
        raise HTTPException(400, "Organising company name must be 100 characters or fewer")
    normalized_contacts = _normalized_recipient_inputs(contacts) if contacts else {}
    if not normalized_contacts and not rejected_contacts:
        raise HTTPException(400, "Add at least one valid or rejected WhatsApp contact")
    if normalized_contacts and not recipient_opt_in_confirmed:
        raise HTTPException(400, "Confirm recipient WhatsApp opt-in before saving this list")
    try:
        require_whatsapp_recipient_capacity(
            active_count=0, activating_count=len(normalized_contacts)
        )
    except WhatsAppRecipientCapacityExceeded as exc:
        raise HTTPException(
            400, f"A WhatsApp list can contain at most {MAX_WHATSAPP_RECIPIENTS} recipients"
        ) from exc
    if not support_contacts:
        raise HTTPException(400, "Add at least one customer support contact")
    normalized_support: dict[str, WhatsAppSupportContactInput] = {}
    for contact in support_contacts:
        normalized = _normalize_phone(contact.phone_number)
        if not normalized:
            raise HTTPException(400, f"Invalid WhatsApp number for support contact {contact.name}")
        # Validate before any inserts, including names supplied by code-owned adapters.
        _clean_required_name(contact.name, "Customer support name")
        normalized_support.setdefault(normalized, contact)
    if len(normalized_support) > 3:
        raise HTTPException(400, "Add no more than three customer support contacts")
    return group_name, company_name, normalized_contacts, normalized_support


async def create_new_broadcast(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    actor_id: uuid.UUID,
    name: str,
    organizing_company_name: str | None,
    contacts: list[WhatsAppRecipientInput],
    rejected_contacts: list[WhatsAppRejectedContactInput],
    support_contacts: list[WhatsAppSupportContactInput],
    recipient_opt_in_confirmed: bool,
    declared_field_keys: list[str],
) -> WhatsAppBroadcastGroupModel:
    """Caller establishes live actor/agency authority before calling this helper."""
    group_name, company_name, normalized_contacts, normalized_support = validate_new_broadcast(
        name=name,
        organizing_company_name=organizing_company_name,
        contacts=contacts,
        rejected_contacts=rejected_contacts,
        support_contacts=support_contacts,
        recipient_opt_in_confirmed=recipient_opt_in_confirmed,
    )
    now = datetime.now(UTC)
    group = WhatsAppBroadcastGroupModel(
        agency_id=agency_id,
        name=group_name,
        organizing_company_name=company_name,
        recipient_opt_in_confirmed_at=now if normalized_contacts else None,
        imported_field_keys=_imported_field_keys_for_contacts(
            declared_keys=declared_field_keys,
            contacts=[*contacts, *rejected_contacts],
        ),
        created_by_user_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    session.add(group)
    await session.flush()
    recipient_orders, rejected_orders = _new_roster_display_orders(
        normalized_contacts=normalized_contacts,
        rejected_contacts=rejected_contacts,
        existing_by_phone={},
        existing_by_fingerprint={},
        start_order=1,
    )
    for normalized, recipient in normalized_contacts.items():
        session.add(
            WhatsAppBroadcastRecipientModel(
                broadcast_group_id=group.id,
                agency_id=agency_id,
                name=_clean_name(recipient.name),
                phone_number=recipient.phone_number.strip(),
                normalized_phone_number=normalized,
                imported_fields=recipient.imported_fields,
                display_order=recipient_orders[normalized],
                created_at=now,
            )
        )
    _add_rejected_contact_models(
        session=session,
        group=group,
        contacts=rejected_contacts,
        existing_by_fingerprint={},
        now=now,
        display_orders_by_fingerprint=rejected_orders,
    )
    for sort_order, (normalized, contact) in enumerate(normalized_support.items()):
        session.add(
            WhatsAppBroadcastSupportContactModel(
                broadcast_group_id=group.id,
                agency_id=agency_id,
                name=_clean_required_name(contact.name, "Customer support name"),
                phone_number=contact.phone_number.strip(),
                normalized_phone_number=normalized,
                sort_order=sort_order,
                created_at=now,
            )
        )
    await session.flush()
    return group
