"""Rejected source-row identity, validation and bounded persistence staging."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRejectedContactModel,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    _WHATSAPP_CONTACT_REJECTION_REASONS,
    MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP,
)
from app.presentation.api.v1.routes.whatsapp_imported_fields import _safe_imported_fields
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppRejectedContactInput,
)


def _rejected_contact_fingerprint(
    contact: WhatsAppRejectedContactInput,
) -> str:
    payload = json.dumps(
        [
            contact.source_file_name,
            contact.sheet_name,
            contact.row_number,
            contact.raw_name,
            contact.raw_phone_number,
            contact.reason_code,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_rejected_contacts(value: str) -> list[WhatsAppRejectedContactInput]:
    try:
        parsed = json.loads(value or "[]")
        if not isinstance(parsed, list):
            raise TypeError
        if len(parsed) > MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "A WhatsApp list can contain at most "
                    f"{MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP} rejected contacts"
                ),
            )
        contacts: list[WhatsAppRejectedContactInput] = []
        fingerprints: set[str] = set()
        for item in parsed:
            contact = WhatsAppRejectedContactInput(**item)
            source_file_name = (
                contact.source_file_name.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()
            )
            sheet_name = contact.sheet_name.strip()
            raw_name = (contact.raw_name or "").strip() or None
            raw_phone_number = (contact.raw_phone_number or "").strip() or None
            if not source_file_name:
                raise ValueError("source_file_name is empty")
            if not sheet_name:
                raise ValueError("sheet_name is empty")
            normalized = WhatsAppRejectedContactInput(
                source_file_name=source_file_name,
                sheet_name=sheet_name,
                row_number=contact.row_number,
                raw_name=raw_name,
                raw_phone_number=raw_phone_number,
                imported_fields=_safe_imported_fields(contact.imported_fields),
                reason_code=contact.reason_code,
            )
            fingerprint = _rejected_contact_fingerprint(normalized)
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            contacts.append(normalized)
        return contacts
    except HTTPException:
        raise
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid rejected WhatsApp contact list",
        ) from exc


def _add_rejected_contact_models(
    *,
    session: AsyncSession,
    group: WhatsAppBroadcastGroupModel,
    contacts: list[WhatsAppRejectedContactInput],
    existing_by_fingerprint: dict[
        str,
        WhatsAppBroadcastRejectedContactModel,
    ],
    now: datetime,
    display_orders_by_fingerprint: dict[str, int] | None = None,
) -> int:
    display_orders_by_fingerprint = display_orders_by_fingerprint or {}
    new_contacts: list[WhatsAppRejectedContactInput] = []
    pending_fingerprints: set[str] = set()
    for contact in contacts:
        fingerprint = _rejected_contact_fingerprint(contact)
        existing = existing_by_fingerprint.get(fingerprint)
        if existing is None:
            if fingerprint not in pending_fingerprints:
                pending_fingerprints.add(fingerprint)
                new_contacts.append(contact)
            continue
        # A repeated import remains one rejected row, but can enrich a record
        # created before imported spreadsheet fields were persisted.
        merged_fields = dict(existing.imported_fields or {})
        merged_fields.update(contact.imported_fields)
        existing.imported_fields = _safe_imported_fields(merged_fields)
    if len(existing_by_fingerprint) + len(new_contacts) > MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A WhatsApp list can contain at most "
                f"{MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP} rejected contacts"
            ),
        )
    for contact in new_contacts:
        fingerprint = _rejected_contact_fingerprint(contact)
        model = WhatsAppBroadcastRejectedContactModel(
            broadcast_group_id=group.id,
            agency_id=group.agency_id,
            source_file_name=contact.source_file_name,
            sheet_name=contact.sheet_name,
            row_number=contact.row_number,
            raw_name=contact.raw_name,
            raw_phone_number=contact.raw_phone_number,
            imported_fields=_safe_imported_fields(contact.imported_fields),
            display_order=display_orders_by_fingerprint.get(fingerprint),
            reason_code=contact.reason_code,
            reason=_WHATSAPP_CONTACT_REJECTION_REASONS[contact.reason_code],
            fingerprint=fingerprint,
            created_at=now,
        )
        existing_by_fingerprint[fingerprint] = model
        session.add(model)
    return len(new_contacts)
