"""Insert-only source contacts and delivery destinations; no revival or updates."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.application.mcp.broadcast_link_source import (
    MAX_LINKS,
    MAX_SOURCE_ROWS,
    BroadcastLinkSource,
)
from app.application.mcp.operations import MCPOperationError
from app.application.use_cases.whatsapp.recipient_capacity import (
    WhatsAppRecipientCapacityExceeded,
    require_whatsapp_recipient_capacity,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSourceContactModel,
)


@dataclass(frozen=True, slots=True)
class BroadcastLinkPlan:
    recipients: list[WhatsAppBroadcastRecipientModel]
    contacts: list[WhatsAppBroadcastSourceContactModel]
    retained_contacts: list[WhatsAppBroadcastSourceContactModel]
    retained_recipients: list[WhatsAppBroadcastRecipientModel]
    matching_fields: list[str] | None


def _active(row: WhatsAppBroadcastRecipientModel) -> bool:
    return (
        row.removed_at is None
        and row.merged_into_recipient_id is None
        and row.suppressed_by_roster_resolution_id is None
    )


def _source_values(row: dict[str, Any], recipient_id: uuid.UUID | None) -> dict[str, Any]:
    return {
        "name": row["name"],
        "raw_phone_number": row["phone_number"],
        "normalized_phone_number": row["normalized_phone_number"],
        "issue": row["issue"],
        "imported_fields": row["imported_fields"],
        "recipient_id": recipient_id,
    }


def _destinations(
    source: BroadcastLinkSource,
) -> tuple[dict[str, WhatsAppBroadcastRecipientModel], list[WhatsAppBroadcastRecipientModel]]:
    by_phone = {row.normalized_phone_number: row for row in source.recipients}
    added = []
    display_order = max((row.display_order or 0 for row in source.recipients), default=0)
    for desired in source.snapshot["recipients"]:
        phone = desired["phone_number"]
        if phone in source.blocked_phones:
            raise MCPOperationError("broadcast_link_replacement_conflict")
        if phone in by_phone:
            if not _active(by_phone[phone]):
                raise MCPOperationError("broadcast_link_recipient_unavailable")
            continue
        display_order += 1
        row = WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(),
            agency_id=source.group.agency_id,
            broadcast_group_id=source.broadcast.id,
            name=desired["name"],
            phone_number=phone,
            normalized_phone_number=phone,
            imported_fields=desired["imported_fields"],
            display_order=display_order,
            is_source_managed=True,
        )
        by_phone[phone] = row
        added.append(row)
    return by_phone, added


def _contacts(
    source: BroadcastLinkSource, by_phone: dict[str, WhatsAppBroadcastRecipientModel]
) -> tuple[list[WhatsAppBroadcastSourceContactModel], list[WhatsAppBroadcastSourceContactModel]]:
    existing = {
        row.source_submission_id: row
        for row in source.contacts
        if row.source_group_id == source.group.id
    }
    added, retained = [], []
    for desired in source.snapshot["contacts"]:
        submission_id = uuid.UUID(desired["source_submission_id"])
        target = (
            by_phone.get(desired["normalized_phone_number"]) if desired["issue"] is None else None
        )
        values = _source_values(desired, target.id if target else None)
        row = existing.get(submission_id)
        if row is not None:
            if any(getattr(row, name) != value for name, value in values.items()):
                raise MCPOperationError("broadcast_link_retained_contact_conflict")
            retained.append(row)
        else:
            added.append(
                WhatsAppBroadcastSourceContactModel(
                    id=uuid.uuid4(),
                    agency_id=source.group.agency_id,
                    broadcast_group_id=source.broadcast.id,
                    source_group_id=source.group.id,
                    source_submission_id=submission_id,
                    **values,
                )
            )
    return added, retained


def prepare_link_plan(
    source: BroadcastLinkSource, matching_fields: list[str] | None
) -> BroadcastLinkPlan:
    existing = source.existing_link
    if existing is not None:
        if existing.matching_field_keys != matching_fields:
            raise MCPOperationError("broadcast_link_existing_configuration")
        return BroadcastLinkPlan([], [], [], [], matching_fields)
    if len(source.links) >= MAX_LINKS:
        raise MCPOperationError("broadcast_link_scope_too_large")
    if any(
        row.normalized_phone_number in source.blocked_phones and _active(row)
        for row in source.recipients
    ):
        raise MCPOperationError("broadcast_link_replacement_conflict")
    if not source.group.import_only:
        return BroadcastLinkPlan([], [], [], [], matching_fields)
    by_phone, recipients = _destinations(source)
    contacts, retained = _contacts(source, by_phone)
    if (
        len(source.contacts) + len(contacts) > MAX_SOURCE_ROWS
        or len(source.recipients) + len(recipients) > MAX_SOURCE_ROWS
    ):
        raise MCPOperationError("broadcast_link_scope_too_large")
    try:
        require_whatsapp_recipient_capacity(
            active_count=sum(row.removed_at is None for row in source.recipients),
            activating_count=len(recipients),
            broadcast_group_id=source.broadcast.id,
        )
    except WhatsAppRecipientCapacityExceeded as exc:
        raise MCPOperationError("broadcast_link_recipient_capacity") from exc
    used = {row.recipient_id for row in [*contacts, *retained] if row.recipient_id is not None}
    return BroadcastLinkPlan(
        recipients,
        contacts,
        retained,
        [row for row in source.recipients if row.id in used],
        matching_fields,
    )
