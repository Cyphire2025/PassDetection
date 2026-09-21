"""Exact submitted/imported/linked destinations for approved travellers."""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_phone_authority import authoritative_submission_phone
from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.application.use_cases.whatsapp.group_submission_matching import compare_group_submissions
from app.application.use_cases.whatsapp.imported_broadcast_phone import (
    explicit_imported_broadcast_phone,
    has_public_collection_contact,
    raw_explicit_imported_broadcast_phone,
)
from app.application.use_cases.whatsapp.private_delivery_identity import is_private_delivery_match
from app.domain.entities.entities import (
    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES,
    PassportSubmission,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSourceContactModel,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    matching_field_keys_from_storage,
    recipient_comparison_from_model,
    submission_comparison_from_model,
)


@dataclass(frozen=True, slots=True)
class TravellerDestination:
    passenger_id: uuid.UUID
    passenger_name: str
    phone_number: str | None
    reason: str | None = None
    phone_source: Literal["submission", "imported_group", "linked_broadcast"] | None = None
    recipient_id: uuid.UUID | None = None
    broadcast_group_id: uuid.UUID | None = None
    broadcast_name: str | None = None


def _known_import(passenger: PassportSubmissionModel | PassportSubmission) -> bool:
    return (passenger.confidence_score or {}).get("source") == "excel_import" or str(
        passenger.image_s3_key or ""
    ).startswith("excel-imports/")


def resolve_traveller_destination(
    passenger: PassportSubmissionModel | PassportSubmission, *, import_only: bool,
) -> TravellerDestination:
    """Resolve one exact passenger row without changing login or OTP authority.

    Explicit imported contacts belong to this exact group row, in either group
    mode. They may be intentionally shared; no recipient name/phone inference is
    needed. Completed public details always win, including an invalid/cleared
    contact that must not revive older imported metadata.
    """
    phone = authoritative_submission_phone(passenger)
    if phone is not None:
        return TravellerDestination(
            passenger_id=passenger.id, passenger_name=passenger.client_name,
            phone_number=phone, phone_source="submission",
        )
    if has_public_collection_contact(passenger):
        return TravellerDestination(
            passenger_id=passenger.id, passenger_name=passenger.client_name,
            phone_number=None, phone_source="submission",
            reason=(
                "Add a valid WhatsApp number in this traveller's completed passport "
                "submission before sending their welcome or documents."
            ),
        )
    if not _known_import(passenger) and passenger.client_phone:
        # Preserve legacy entered client contacts that predate public completion
        # metadata. Excel's generic client_phone alone is deliberately excluded.
        phone = normalize_whatsapp_phone(passenger.client_phone)
        return TravellerDestination(
            passenger_id=passenger.id, passenger_name=passenger.client_name,
            phone_number=phone, phone_source="submission",
            reason=None if phone else "Correct this traveller's submitted WhatsApp number before sending.",
        )
    metadata = passenger.staff_metadata or {}
    _raw_phone, has_column = raw_explicit_imported_broadcast_phone(metadata)
    if has_column:
        phone, _has_value = explicit_imported_broadcast_phone(metadata)
        return TravellerDestination(
            passenger_id=passenger.id, passenger_name=passenger.client_name,
            phone_number=phone, phone_source="imported_group",
            reason=None if phone else (
                "Correct this traveller's imported WhatsApp number. The selected "
                "Verified WhatsApp Numbers or Upload Phone column is empty, invalid, "
                "or contains conflicting numbers."
            ),
        )
    return TravellerDestination(
        passenger_id=passenger.id, passenger_name=passenger.client_name,
        phone_number=None,
        reason=(
            "Add this traveller's number to the group's Verified WhatsApp Numbers "
            "or Upload Phone column, or link an unambiguous matching broadcast contact."
            if import_only else
            "Add this traveller's submitted WhatsApp number, or link a broadcast "
            "contact with an unambiguous private-delivery identity match."
        ),
    )


async def load_traveller_destinations(
    session: AsyncSession, *, agency_id: uuid.UUID, group_id: uuid.UUID, lock: bool = False,
) -> list[TravellerDestination]:
    """Resolve current source evidence using the same policy at preview and send.

    Locks follow group, broadcasts/links, recipients, source contacts, passengers.
    Only the caller's explicitly scoped group participates. Missing own contacts
    may use established private-grade matching; ambiguous names never choose a
    destination. No collection, OTP or login provenance is written here.
    """
    group_statement = select(ClientGroupModel).where(
        ClientGroupModel.id == group_id,
        ClientGroupModel.agency_id == agency_id,
        ClientGroupModel.deleted_at.is_(None),
        ClientGroupModel.status.not_in(("archived", "deleted")),
    )
    if lock:
        group_statement = group_statement.with_for_update().execution_options(populate_existing=True)
    group = (await session.scalars(group_statement)).one_or_none()
    if group is None:
        return []
    links_statement = select(ClientGroupWhatsAppBroadcastLinkModel, WhatsAppBroadcastGroupModel).join(
        WhatsAppBroadcastGroupModel,
        WhatsAppBroadcastGroupModel.id == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
    ).where(
        ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
        WhatsAppBroadcastGroupModel.agency_id == agency_id,
        WhatsAppBroadcastGroupModel.archived_at.is_(None),
        WhatsAppBroadcastGroupModel.recipient_opt_in_confirmed_at.is_not(None),
    ).order_by(WhatsAppBroadcastGroupModel.id)
    if lock:
        links_statement = links_statement.with_for_update().execution_options(populate_existing=True)
    links = (await session.execute(links_statement)).all()
    broadcasts = {broadcast.id: broadcast for _link, broadcast in links}
    matching_fields = {
        broadcast.id: matching_field_keys_from_storage(link.matching_field_keys)
        for link, broadcast in links
    }
    recipients_statement = select(WhatsAppBroadcastRecipientModel).where(
        WhatsAppBroadcastRecipientModel.agency_id == agency_id,
        WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(broadcasts),
        WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
    ).order_by(WhatsAppBroadcastRecipientModel.broadcast_group_id, WhatsAppBroadcastRecipientModel.id)
    source_statement = select(WhatsAppBroadcastSourceContactModel).where(
        WhatsAppBroadcastSourceContactModel.agency_id == agency_id,
        WhatsAppBroadcastSourceContactModel.source_group_id == group_id,
        WhatsAppBroadcastSourceContactModel.broadcast_group_id.in_(broadcasts),
    ).order_by(WhatsAppBroadcastSourceContactModel.broadcast_group_id, WhatsAppBroadcastSourceContactModel.id)
    passengers_statement = select(PassportSubmissionModel).where(
        PassportSubmissionModel.agency_id == agency_id,
        PassportSubmissionModel.group_id == group_id,
        PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
        operational_roster_member(),
    ).order_by(PassportSubmissionModel.id)
    if lock:
        recipients_statement = recipients_statement.with_for_update().execution_options(populate_existing=True)
        source_statement = source_statement.with_for_update().execution_options(populate_existing=True)
        passengers_statement = passengers_statement.with_for_update().execution_options(populate_existing=True)
    recipients = list((await session.scalars(recipients_statement)).all()) if broadcasts else []
    sources = list((await session.scalars(source_statement)).all()) if broadcasts else []
    passengers = list((await session.scalars(passengers_statement)).all())
    own_destinations = [
        resolve_traveller_destination(passenger, import_only=group.import_only)
        for passenger in passengers
    ]
    recipients_by_id = {recipient.id: recipient for recipient in recipients}
    recipients_by_phone: dict[str, list[WhatsAppBroadcastRecipientModel]] = defaultdict(list)
    for recipient in recipients:
        phone = normalize_whatsapp_phone(recipient.normalized_phone_number)
        if phone:
            recipients_by_phone[phone].append(recipient)
    exact_sources: dict[uuid.UUID, list[WhatsAppBroadcastSourceContactModel]] = defaultdict(list)
    for source in sources:
        exact_sources[source.source_submission_id].append(source)
    fallback_ids = {row.passenger_id for row in own_destinations if row.phone_source is None}
    matched_recipients: dict[uuid.UUID, list[WhatsAppBroadcastRecipientModel]] = defaultdict(list)
    if fallback_ids and recipients:
        comparison_submissions = []
        for passenger in passengers:
            comparison = submission_comparison_from_model(passenger)
            if _known_import(passenger) and not has_public_collection_contact(passenger):
                comparison = replace(comparison, client_phone=None)
            comparison_submissions.append(comparison)
        broadcast_names = {key: value.name for key, value in broadcasts.items()}
        comparisons = [recipient_comparison_from_model(
            recipient, broadcast_names, matching_fields,
        ) for recipient in recipients]
        rows, _counts = await asyncio.to_thread(compare_group_submissions, comparisons, comparison_submissions)
        for row in rows:
            if not is_private_delivery_match(row) or row.submission_ids[0] not in fallback_ids:
                continue
            for recipient_id in row.recipient_ids:
                recipient = recipients_by_id.get(recipient_id)
                if recipient is not None:
                    matched_recipients[row.submission_ids[0]].append(recipient)
    resolved: list[TravellerDestination] = []
    for destination in own_destinations:
        selected: WhatsAppBroadcastRecipientModel | None = None
        if destination.phone_number:
            for source in exact_sources.get(destination.passenger_id, []):
                candidate = recipients_by_id.get(source.recipient_id) if source.recipient_id else None
                if (
                    candidate is not None
                    and candidate.broadcast_group_id == source.broadcast_group_id
                    and normalize_whatsapp_phone(source.normalized_phone_number) == destination.phone_number
                    and normalize_whatsapp_phone(candidate.normalized_phone_number) == destination.phone_number
                ):
                    selected = candidate
                    break
            if selected is None:
                selected = next(iter(recipients_by_phone.get(destination.phone_number, [])), None)
        elif destination.phone_source is None:
            candidates = matched_recipients.get(destination.passenger_id, [])
            candidate_phones = {normalize_whatsapp_phone(item.normalized_phone_number) for item in candidates}
            if len(candidate_phones) == 1 and None not in candidate_phones:
                selected = min(candidates, key=lambda item: (str(item.broadcast_group_id), str(item.id)))
                destination = replace(destination, phone_number=candidate_phones.pop(),
                                      phone_source="linked_broadcast", reason=None)
            elif len(candidate_phones) > 1:
                destination = replace(destination, reason=(
                    "Linked broadcast contacts match this traveller to different WhatsApp numbers. "
                    "Correct the conflicting contacts or enter the traveller's own number before sending."
                ))
        if selected is not None:
            broadcast = broadcasts[selected.broadcast_group_id]
            destination = replace(destination, recipient_id=selected.id,
                                  broadcast_group_id=broadcast.id, broadcast_name=broadcast.name)
        elif destination.phone_number and broadcasts:
            broadcast = next(iter(broadcasts.values()))
            destination = replace(destination, broadcast_group_id=broadcast.id, broadcast_name=broadcast.name)
        resolved.append(destination)
    return resolved
