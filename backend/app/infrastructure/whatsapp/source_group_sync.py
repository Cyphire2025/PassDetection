"""One-way group roster synchronization; traveller rows and delivery phones are distinct."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.recipient_capacity import MAX_WHATSAPP_RECIPIENTS
from app.application.use_cases.whatsapp.source_group_contacts import build_source_contacts
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.domain.exceptions.exceptions import ConflictError
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSourceContactModel,
    WhatsAppTravellerPhoneOverrideModel,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_phone_numbers_for_broadcast,
    suppress_active_replacement_recipients,
)
from app.infrastructure.whatsapp.phone_overrides import (
    load_valid_traveller_phone_overrides,
    source_phone_fingerprint,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
    prepare_private_delivery_identity_mutation,
)

Contact = WhatsAppBroadcastSourceContactModel
Recipient = WhatsAppBroadcastRecipientModel
_CONTACT_FIELDS = (
    "name", "raw_phone_number", "normalized_phone_number", "issue", "imported_fields", "recipient_id",
)


def _contact_values(contact: Contact) -> dict[str, Any]:
    return {field: getattr(contact, field) for field in _CONTACT_FIELDS}


async def _sync_broadcast(
    session: AsyncSession, *, agency_id: uuid.UUID, group_id: uuid.UUID,
    broadcast: WhatsAppBroadcastGroupModel, desired: list[dict[str, Any]],
) -> dict[str, int]:
    now = datetime.now(tz=UTC)
    existing_contacts = list((await session.scalars(
        select(Contact).where(
            Contact.agency_id == agency_id, Contact.broadcast_group_id == broadcast.id,
        ).order_by(Contact.created_at, Contact.id)
    )).all())
    own = {row.source_submission_id: row for row in existing_contacts if row.source_group_id == group_id}
    desired_ids = {uuid.UUID(row["source_submission_id"]) for row in desired}
    deleted = [row for key, row in own.items() if key not in desired_ids]
    plans: list[tuple[Contact, dict[str, Any], bool]] = [
        (row, _contact_values(row), False)
        for row in existing_contacts if row.source_group_id != group_id
    ]
    for source in desired:
        submission_id = uuid.UUID(source["source_submission_id"])
        row = own.get(submission_id)
        is_new = row is None
        if row is None:
            row = Contact(
                id=uuid.uuid4(), agency_id=agency_id, broadcast_group_id=broadcast.id,
                source_group_id=group_id, source_submission_id=submission_id,
                created_at=now, updated_at=now,
            )
        plans.append((row, {
            "name": source["name"], "raw_phone_number": source["phone_number"],
            "normalized_phone_number": source["normalized_phone_number"],
            "issue": source["issue"], "imported_fields": source["imported_fields"],
            "recipient_id": None,
        }, is_new))
    # The representative for a shared phone must not alternate depending on
    # which linked source happened to change most recently.
    plans.sort(key=lambda plan: (str(plan[0].source_group_id), str(plan[0].source_submission_id)))

    recipients = list((await session.scalars(select(Recipient).where(
        Recipient.agency_id == agency_id, Recipient.broadcast_group_id == broadcast.id,
    ).order_by(Recipient.display_order, Recipient.created_at, Recipient.id).with_for_update())).all())
    by_phone = {row.normalized_phone_number: row for row in recipients}
    overrides = await load_valid_traveller_phone_overrides(
        session, agency_id=agency_id, broadcast_group_ids={broadcast.id},
        require_active_groups=False, include_inactive_targets=True,
    )
    effective_phones: dict[uuid.UUID, str | None] = {}
    override_target_phones: set[str] = set()
    for row, values, _is_new in plans:
        target = overrides.get((broadcast.id, row.source_submission_id))
        phone = values["normalized_phone_number"]
        if target is not None:
            if (target.removed_at is not None or target.merged_into_recipient_id is not None
                    or target.suppressed_by_roster_resolution_id is not None):
                phone = None
                values["issue"] = "override_unavailable"
            else:
                phone = target.normalized_phone_number
                if values["issue"] in {
                    "missing_phone", "invalid_phone", "unverified_phone", "recipient_limit", "override_unavailable",
                }:
                    values["issue"] = None
        effective_phones[row.id] = phone
    for target in overrides.values():
        if (target.removed_at is None and target.merged_into_recipient_id is None
                and target.suppressed_by_roster_resolution_id is None):
            override_target_phones.add(target.normalized_phone_number)
    blocked = await active_replacement_phone_numbers_for_broadcast(
        session, agency_id=agency_id, broadcast_group_id=broadcast.id,
    )
    representatives: dict[str, dict[str, Any]] = {}
    original_representatives: set[str] = set()
    for row, values, _ in plans:
        # A previously full broadcast may have room after source removals.
        if values["issue"] == "recipient_limit":
            values["issue"] = None
        phone = effective_phones[row.id]
        if phone and values["issue"] is None:
            if phone not in representatives or (
                phone == values["normalized_phone_number"] and phone not in original_representatives
            ):
                representatives[phone] = values
            if phone == values["normalized_phone_number"]:
                original_representatives.add(phone)
    manual_active = {
        row.normalized_phone_number for row in recipients
        if not row.is_source_managed and row.removed_at is None and row.merged_into_recipient_id is None
    }
    selected = manual_active | override_target_phones
    # Existing delivery identities keep their places before newly added phones.
    source_order = {phone: index for index, phone in enumerate(representatives)}
    ordered_phones = sorted(representatives, key=lambda phone: (
        not (phone in by_phone and by_phone[phone].removed_at is None),
        source_order[phone],
    ))
    admitted: set[str] = set()
    for phone in ordered_phones:
        if phone in blocked or phone in selected or len(selected) < MAX_WHATSAPP_RECIPIENTS:
            admitted.add(phone)
            if phone not in blocked:
                selected.add(phone)

    recipient_plans: list[tuple[Recipient, dict[str, Any], bool]] = []
    display_order = max((row.display_order or 0 for row in recipients), default=0)
    for phone in ordered_phones:
        if phone not in admitted:
            continue
        values = representatives[phone]
        recipient = by_phone.get(phone)
        is_new = recipient is None
        if recipient is None:
            display_order += 1
            recipient = Recipient(
                id=uuid.uuid4(), agency_id=agency_id, broadcast_group_id=broadcast.id,
                normalized_phone_number=phone, created_at=now, display_order=display_order,
            )
            by_phone[phone] = recipient
        changes: dict[str, Any] = {}
        # Active manual contacts keep their editing and lifecycle ownership.
        if is_new or recipient.is_source_managed or recipient.removed_at is not None:
            changes = {
                "name": values["name"], "phone_number": phone,
                "imported_fields": values["imported_fields"], "is_source_managed": True,
                "removed_at": (recipient.removed_at or now) if phone in blocked else None,
            }
            if phone not in blocked:
                changes["suppressed_by_roster_resolution_id"] = None
                changes["merged_into_recipient_id"] = None
        recipient_plans.append((recipient, changes, is_new))
    for recipient in recipients:
        if (recipient.is_source_managed
                and recipient.normalized_phone_number not in (admitted | override_target_phones)
                and recipient.removed_at is None):
            recipient_plans.append((recipient, {"removed_at": now}, False))
    for row, values, _ in plans:
        phone = effective_phones[row.id]
        values["recipient_id"] = None
        if phone and values["issue"] is None:
            if phone in admitted:
                values["recipient_id"] = by_phone[phone].id
            else:
                values["issue"] = "recipient_limit"

    changed_contacts = [
        (row, values, is_new) for row, values, is_new in plans
        if is_new or any(getattr(row, key) != value for key, value in values.items())
    ]
    changed_recipients = [
        (row, values, is_new) for row, values, is_new in recipient_plans
        if is_new or any(getattr(row, key) != value for key, value in values.items())
    ]
    result = {"broadcasts": 1, "contacts": len(desired), "added": 0, "updated": 0, "removed": 0}
    if not (deleted or changed_contacts or changed_recipients):
        return result
    try:
        await prepare_private_delivery_identity_mutation(
            session, agency_id=agency_id, broadcast_group_ids={broadcast.id}, cancel_queued=True,
            cancellation_reason="Source group contacts changed; queue this private delivery again.",
        )
    except PrivateDeliveryMutationBlocked as exc:
        raise ConflictError(str(exc), code="WHATSAPP_SOURCE_SYNC_DELIVERY_ACTIVE") from exc
    for row in deleted:
        await session.delete(row)
    for changed_recipient, values, is_new in changed_recipients:
        for key, value in values.items():
            setattr(changed_recipient, key, value)
        session.add(changed_recipient)
        result["added" if is_new else "updated"] += 1
        if values.get("removed_at") is not None:
            result["removed"] += 1
    # Materialize recipient FKs before inserting per-traveller associations.
    await session.flush()
    for row, values, _ in changed_contacts:
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = now
        session.add(row)
    broadcast.updated_at = now
    broadcast.imported_field_keys = sorted(set(broadcast.imported_field_keys or []) | {
        key for _, values, _ in plans for key in values["imported_fields"]
    })
    await session.flush()
    await suppress_active_replacement_recipients(
        session, agency_id=agency_id, broadcast_group_ids=[broadcast.id], now=now,
    )
    return result


async def sync_group_broadcast_contacts(
    session: AsyncSession, *, agency_id: uuid.UUID, group_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
    affected_broadcast_ids: Sequence[uuid.UUID] = (),
) -> dict[str, int]:
    """Synchronize source-owned roster state within the caller's transaction.

    No commits, messages, or source passport writes occur here. Callers authorize
    source mutations; tenant predicates are enforced again on every stored row.
    """
    await session.flush()
    source = await session.scalar(select(ClientGroupModel).where(
        ClientGroupModel.id == group_id, ClientGroupModel.agency_id == agency_id,
    ).with_for_update())
    links = list((await session.scalars(select(ClientGroupWhatsAppBroadcastLinkModel).where(
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
        ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
    ))).all())
    eligible = {
        link.broadcast_group_id for link in links
        if source is not None and source.deleted_at is None
        and (source.import_only or link.sync_contacts_from_group)
    }
    if source is not None and source.import_only:
        for link in links:
            link.sync_contacts_from_group = True
    old_ids = set((await session.scalars(select(Contact.broadcast_group_id).where(
        Contact.agency_id == agency_id, Contact.source_group_id == group_id,
    ).distinct())).all())
    overrides = list((await session.scalars(select(WhatsAppTravellerPhoneOverrideModel).where(
        WhatsAppTravellerPhoneOverrideModel.agency_id == agency_id,
        WhatsAppTravellerPhoneOverrideModel.group_id == group_id,
    ))).all())
    affected = eligible | old_ids | set(affected_broadcast_ids) | {
        override.broadcast_group_id for override in overrides
    }
    result = dict.fromkeys(("broadcasts", "contacts", "added", "updated", "removed"), 0)
    if not affected:
        return result
    broadcasts = list((await session.scalars(select(WhatsAppBroadcastGroupModel).where(
        WhatsAppBroadcastGroupModel.agency_id == agency_id,
        WhatsAppBroadcastGroupModel.id.in_(affected),
    ).order_by(WhatsAppBroadcastGroupModel.id).with_for_update())).all())
    contacts: list[dict[str, Any]] = []
    submissions: list[PassportSubmissionModel] = []
    if (eligible or overrides) and source is not None and source.deleted_at is None:
        # Some mutations already hold a passport lock. Read the committed roster
        # without acquiring more passport locks after taking the broadcast lock.
        submissions = list((await session.scalars(select(PassportSubmissionModel).where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
            operational_roster_member(),
        ).order_by(PassportSubmissionModel.created_at, PassportSubmissionModel.id))).all())
        if eligible:
            contacts = build_source_contacts(
                group_id, source.name, submissions, import_only=source.import_only,
            )["contacts"]
    by_id = {submission.id: submission for submission in submissions}
    linked_ids = {link.broadcast_group_id for link in links}
    invalid_overrides = [override for override in overrides if (
        source is None or source.deleted_at is not None or override.broadcast_group_id not in linked_ids
        or (passenger := by_id.get(override.passenger_id)) is None
        or override.source_phone_fingerprint != source_phone_fingerprint(passenger)
    )]
    if invalid_overrides:
        try:
            await prepare_private_delivery_identity_mutation(
                session, agency_id=agency_id, group_id=group_id, cancel_queued=True,
                cancellation_reason="The traveller's source phone or broadcast link changed; review this private delivery again.",
            )
        except PrivateDeliveryMutationBlocked as exc:
            raise ConflictError(str(exc), code="WHATSAPP_SOURCE_SYNC_DELIVERY_ACTIVE") from exc
        for override in invalid_overrides:
            await session.delete(override)
        await session.flush()
    for broadcast in broadcasts:
        counts = await _sync_broadcast(
            session, agency_id=agency_id, group_id=group_id, broadcast=broadcast,
            desired=contacts if broadcast.id in eligible else [],
        )
        for key, count in counts.items():
            result[key] += count
    return result
