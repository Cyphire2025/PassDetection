"""Exact broadcast-only phone corrections, separate from passport/OTP authority."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_phone_authority import authoritative_submission_phone
from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.application.use_cases.whatsapp.group_submission_matching import compare_group_submissions
from app.application.use_cases.whatsapp.imported_broadcast_phone import (
    explicit_imported_broadcast_phone,
    has_public_collection_contact,
    imported_phone_column_priority,
)
from app.application.use_cases.whatsapp.private_delivery_identity import is_private_delivery_match
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.domain.exceptions.exceptions import ConflictError
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSourceContactModel,
    WhatsAppTravellerPhoneOverrideModel,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    matching_field_keys_from_storage,
    recipient_comparison_from_model,
    submission_comparison_from_model,
)


def _known_import(passenger: Any) -> bool:
    return (passenger.confidence_score or {}).get("source") == "excel_import" or str(
        passenger.image_s3_key or "",
    ).startswith("excel-imports/")


def _phone_value(value: object) -> str:
    raw = str(value or "").strip()
    return normalize_whatsapp_phone(raw) or raw


def source_phone_fingerprint(passenger: Any) -> str:
    """Hash only the winning phone and its provenance, not unrelated edits.

    Invalid/cleared winning values remain meaningful. A later completed public
    contact or a change from Upload Phone to Verified WhatsApp invalidates an
    older correction even if both happened to hold the same digits.
    """
    if has_public_collection_contact(passenger):
        value: object = ["public", _phone_value(passenger.client_phone)]
    elif not _known_import(passenger) and passenger.client_phone:
        value = ["entered", _phone_value(passenger.client_phone)]
    else:
        columns = [
            (priority, _phone_value(raw))
            for key, raw in (passenger.staff_metadata or {}).items()
            if (priority := imported_phone_column_priority(key)) is not None
        ]
        if columns:
            priority = min(rank for rank, _raw in columns)
            winning = {raw for rank, raw in columns if rank == priority and raw}
            value = ["imported", priority, sorted(winning)]
        else:
            value = ["unverified_import" if _known_import(passenger) else "missing",
                     _phone_value(passenger.client_phone)]
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _current_source_phone(passenger: PassportSubmissionModel) -> str | None:
    phone = authoritative_submission_phone(passenger)
    if phone or has_public_collection_contact(passenger):
        return phone
    if not _known_import(passenger) and passenger.client_phone:
        return normalize_whatsapp_phone(passenger.client_phone)
    return explicit_imported_broadcast_phone(passenger.staff_metadata or {})[0]


@dataclass(frozen=True, slots=True)
class TravellerPhoneOverrideSnapshot:
    group_id: uuid.UUID
    passenger_id: uuid.UUID
    source_phone_fingerprint: str


async def linked_recipient_source_group_ids(
    session: AsyncSession, *, agency_id: uuid.UUID, broadcast_group_id: uuid.UUID,
) -> set[uuid.UUID]:
    """Discover the complete group-lock scope before taking the broadcast lock."""
    return set((await session.scalars(select(ClientGroupWhatsAppBroadcastLinkModel.client_group_id).join(
        ClientGroupModel, ClientGroupModel.id == ClientGroupWhatsAppBroadcastLinkModel.client_group_id,
    ).where(
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
        ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == broadcast_group_id,
        ClientGroupModel.agency_id == agency_id,
    ))).all())


async def load_valid_traveller_phone_overrides(
    session: AsyncSession, *, agency_id: uuid.UUID,
    broadcast_group_ids: set[uuid.UUID], require_active_groups: bool = True,
    include_inactive_targets: bool = False,
) -> dict[tuple[uuid.UUID, uuid.UUID], WhatsAppBroadcastRecipientModel]:
    """Bulk effective targets keyed by (broadcast, passenger), without writes.

    Used by source roster projection and sync. Normal document resolution also
    retains invalid-target overrides so it can explain why a correction blocks
    delivery instead of silently reverting to the original phone.
    """
    if not broadcast_group_ids:
        return {}
    statement = select(
        WhatsAppTravellerPhoneOverrideModel, PassportSubmissionModel, WhatsAppBroadcastRecipientModel,
    ).join(
        PassportSubmissionModel,
        PassportSubmissionModel.id == WhatsAppTravellerPhoneOverrideModel.passenger_id,
    ).join(
        ClientGroupModel, ClientGroupModel.id == WhatsAppTravellerPhoneOverrideModel.group_id,
    ).join(
        ClientGroupWhatsAppBroadcastLinkModel,
        (ClientGroupWhatsAppBroadcastLinkModel.client_group_id == WhatsAppTravellerPhoneOverrideModel.group_id)
        & (ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == WhatsAppTravellerPhoneOverrideModel.broadcast_group_id),
    ).join(
        WhatsAppBroadcastRecipientModel,
        WhatsAppBroadcastRecipientModel.id == WhatsAppTravellerPhoneOverrideModel.recipient_id,
    ).where(
        WhatsAppTravellerPhoneOverrideModel.agency_id == agency_id,
        WhatsAppTravellerPhoneOverrideModel.broadcast_group_id.in_(broadcast_group_ids),
        PassportSubmissionModel.agency_id == agency_id,
        PassportSubmissionModel.group_id == WhatsAppTravellerPhoneOverrideModel.group_id,
        PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        operational_roster_member(),
        ClientGroupModel.agency_id == agency_id,
        ClientGroupModel.deleted_at.is_(None),
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
        WhatsAppBroadcastRecipientModel.agency_id == agency_id,
        WhatsAppBroadcastRecipientModel.broadcast_group_id == WhatsAppTravellerPhoneOverrideModel.broadcast_group_id,
    )
    if not include_inactive_targets:
        statement = statement.where(
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            WhatsAppBroadcastRecipientModel.merged_into_recipient_id.is_(None),
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
        )
    if require_active_groups:
        statement = statement.where(ClientGroupModel.status.not_in(("archived", "deleted")))
    return {
        (override.broadcast_group_id, passenger.id): recipient
        for override, passenger, recipient in (await session.execute(statement)).all()
        if override.source_phone_fingerprint == source_phone_fingerprint(passenger)
        and normalize_whatsapp_phone(recipient.normalized_phone_number)
    }


async def snapshot_recipient_traveller_phone_overrides(
    session: AsyncSession, *, agency_id: uuid.UUID, broadcast_group_id: uuid.UUID,
    recipient_id: uuid.UUID,
) -> list[TravellerPhoneOverrideSnapshot]:
    """Capture exact identities before an authorized recipient edit mutates them.

    The caller holds the discovered group locks, broadcast and recipient locks.
    Source association IDs and existing valid overrides may represent shared
    numbers. Otherwise only established private-grade one-to-one matching is
    accepted; names, ambiguous matches and stale source-phone bindings cannot
    create an override.
    """
    links = list((await session.scalars(select(ClientGroupWhatsAppBroadcastLinkModel).join(
        ClientGroupModel, ClientGroupModel.id == ClientGroupWhatsAppBroadcastLinkModel.client_group_id,
    ).where(
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
        ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == broadcast_group_id,
        ClientGroupModel.agency_id == agency_id,
        ClientGroupModel.deleted_at.is_(None),
        ClientGroupModel.status.not_in(("archived", "deleted")),
    ))).all())
    if not links:
        return []
    group_ids = {link.client_group_id for link in links}
    passengers = list((await session.scalars(select(PassportSubmissionModel).where(
        PassportSubmissionModel.agency_id == agency_id,
        PassportSubmissionModel.group_id.in_(group_ids),
        PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        operational_roster_member(),
    ))).all())
    by_id = {passenger.id: passenger for passenger in passengers}
    recipients = list((await session.scalars(select(WhatsAppBroadcastRecipientModel).where(
        WhatsAppBroadcastRecipientModel.agency_id == agency_id,
        WhatsAppBroadcastRecipientModel.broadcast_group_id == broadcast_group_id,
        WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        WhatsAppBroadcastRecipientModel.merged_into_recipient_id.is_(None),
        WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
    ))).all())
    selected = next((row for row in recipients if row.id == recipient_id), None)
    if selected is None:
        return []
    overrides = list((await session.scalars(select(WhatsAppTravellerPhoneOverrideModel).where(
        WhatsAppTravellerPhoneOverrideModel.agency_id == agency_id,
        WhatsAppTravellerPhoneOverrideModel.broadcast_group_id == broadcast_group_id,
        WhatsAppTravellerPhoneOverrideModel.group_id.in_(group_ids),
    ))).all())
    valid_overrides = {
        row.passenger_id: row for row in overrides
        if (passenger := by_id.get(row.passenger_id)) is not None
        and row.group_id == passenger.group_id
        and row.source_phone_fingerprint == source_phone_fingerprint(passenger)
    }
    exact_ids = {passenger_id for passenger_id, row in valid_overrides.items() if row.recipient_id == recipient_id}
    sources = list((await session.scalars(select(WhatsAppBroadcastSourceContactModel).where(
        WhatsAppBroadcastSourceContactModel.agency_id == agency_id,
        WhatsAppBroadcastSourceContactModel.broadcast_group_id == broadcast_group_id,
        WhatsAppBroadcastSourceContactModel.source_group_id.in_(group_ids),
        WhatsAppBroadcastSourceContactModel.recipient_id == recipient_id,
    ))).all())
    for source in sources:
        passenger = by_id.get(source.source_submission_id)
        if passenger is None or passenger.group_id != source.source_group_id:
            continue
        if passenger.id in valid_overrides:
            continue
        phone = _current_source_phone(passenger)
        if phone and phone == source.normalized_phone_number == selected.normalized_phone_number:
            exact_ids.add(passenger.id)
    for link in links:
        comparisons = []
        for passenger in passengers:
            if passenger.group_id != link.client_group_id:
                continue
            comparison = submission_comparison_from_model(passenger)
            if _known_import(passenger) and not has_public_collection_contact(passenger):
                comparison = replace(comparison, client_phone=None)
            comparisons.append(comparison)
        fields = {broadcast_group_id: matching_field_keys_from_storage(link.matching_field_keys)}
        recipient_comparisons = [recipient_comparison_from_model(
            row, {broadcast_group_id: ""}, fields,
        ) for row in recipients]
        rows, _counts = await asyncio.to_thread(compare_group_submissions, recipient_comparisons, comparisons)
        for row in rows:
            if not is_private_delivery_match(row) or recipient_id not in row.recipient_ids:
                continue
            passenger_id = row.submission_ids[0]
            # Existing explicit corrections own this identity; an old imported
            # phone cannot claim it back merely because comparison still matches.
            if passenger_id not in valid_overrides:
                exact_ids.add(passenger_id)
    return [TravellerPhoneOverrideSnapshot(
        group_id=by_id[passenger_id].group_id, passenger_id=passenger_id,
        source_phone_fingerprint=source_phone_fingerprint(by_id[passenger_id]),
    ) for passenger_id in sorted(exact_ids, key=str)]


async def apply_recipient_traveller_phone_overrides(
    session: AsyncSession, *, agency_id: uuid.UUID, broadcast_group_id: uuid.UUID,
    recipient_id: uuid.UUID, snapshots: list[TravellerPhoneOverrideSnapshot],
) -> None:
    """Upsert exact corrections and memberships after the caller's delivery guard.

    Source snapshots are deliberately unchanged. This only writes broadcast
    override rows and existing source-contact recipient FKs; no passport or
    collection/OTP data is modified.
    """
    if not snapshots:
        return
    target = await session.scalar(select(WhatsAppBroadcastRecipientModel).where(
        WhatsAppBroadcastRecipientModel.id == recipient_id,
        WhatsAppBroadcastRecipientModel.agency_id == agency_id,
        WhatsAppBroadcastRecipientModel.broadcast_group_id == broadcast_group_id,
        WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        WhatsAppBroadcastRecipientModel.merged_into_recipient_id.is_(None),
        WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
    ))
    if target is None or not normalize_whatsapp_phone(target.normalized_phone_number):
        raise ConflictError("The corrected WhatsApp destination is no longer active.", code="WHATSAPP_OVERRIDE_TARGET_CHANGED")
    group_ids = await linked_recipient_source_group_ids(
        session, agency_id=agency_id, broadcast_group_id=broadcast_group_id,
    )
    passenger_ids = {snapshot.passenger_id for snapshot in snapshots}
    passengers = {row.id: row for row in (await session.scalars(select(PassportSubmissionModel).where(
        PassportSubmissionModel.agency_id == agency_id,
        PassportSubmissionModel.id.in_(passenger_ids),
        PassportSubmissionModel.group_id.in_(group_ids),
        PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        operational_roster_member(),
    ))).all()}
    for snapshot in snapshots:
        passenger = passengers.get(snapshot.passenger_id)
        if (passenger is None or passenger.group_id != snapshot.group_id
                or source_phone_fingerprint(passenger) != snapshot.source_phone_fingerprint):
            raise ConflictError("The traveller's source contact changed. Refresh before editing the number.",
                                code="WHATSAPP_OVERRIDE_SOURCE_CHANGED")
    existing = {row.passenger_id: row for row in (await session.scalars(select(WhatsAppTravellerPhoneOverrideModel).where(
        WhatsAppTravellerPhoneOverrideModel.agency_id == agency_id,
        WhatsAppTravellerPhoneOverrideModel.broadcast_group_id == broadcast_group_id,
        WhatsAppTravellerPhoneOverrideModel.passenger_id.in_(passenger_ids),
    ).with_for_update())).all()}
    now = datetime.now(tz=UTC)
    for snapshot in snapshots:
        override = existing.get(snapshot.passenger_id)
        if override is None:
            override = WhatsAppTravellerPhoneOverrideModel(
                id=uuid.uuid4(), agency_id=agency_id, broadcast_group_id=broadcast_group_id,
                group_id=snapshot.group_id, passenger_id=snapshot.passenger_id, created_at=now,
            )
        override.recipient_id = recipient_id
        override.source_phone_fingerprint = snapshot.source_phone_fingerprint
        override.updated_at = now
        session.add(override)
    sources = list((await session.scalars(select(WhatsAppBroadcastSourceContactModel).where(
        WhatsAppBroadcastSourceContactModel.agency_id == agency_id,
        WhatsAppBroadcastSourceContactModel.broadcast_group_id == broadcast_group_id,
        WhatsAppBroadcastSourceContactModel.source_submission_id.in_(passenger_ids),
    ).with_for_update())).all())
    for source in sources:
        passenger = passengers.get(source.source_submission_id)
        if passenger is not None and source.source_group_id == passenger.group_id:
            source.recipient_id = recipient_id
            source.updated_at = now
    await session.flush()
