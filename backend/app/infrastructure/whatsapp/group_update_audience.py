"""One authoritative linked-broadcast audience for preview, queue and worker."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_phone_authority import authoritative_submission_phone
from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.application.use_cases.whatsapp.document_updates import ACCEPTED
from app.application.use_cases.whatsapp.group_updates import GroupUpdateContact, GroupUpdateFilters
from app.application.use_cases.whatsapp.imported_broadcast_phone import (
    has_public_collection_contact,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    DistributedDocumentModel,
    DocumentWhatsAppDeliveryModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    load_unresolved_passport_whatsapp_match_context,
)


async def load_group_update_audience(
    session: AsyncSession, *, agency_id: uuid.UUID, group_id: uuid.UUID,
    filters: GroupUpdateFilters, lock: bool = False,
) -> list[GroupUpdateContact]:
    """Combine completed group submissions and active linked broadcast contacts.

    Imported records do not establish submission/phone verification. A completed
    collection uses its authoritative phone even when the Excel number differs.
    Ambiguous identities and submitted records missing that phone never fall back.
    """
    scope = select(ClientGroupModel).join(AgencyModel).where(
        ClientGroupModel.id == group_id, ClientGroupModel.agency_id == agency_id,
        ClientGroupModel.deleted_at.is_(None),
        ClientGroupModel.status.not_in(("archived", "deleted")), AgencyModel.is_active.is_(True),
    )
    if lock:
        scope = scope.with_for_update().execution_options(populate_existing=True)
    if await session.scalar(scope) is None:
        return []
    links = select(ClientGroupWhatsAppBroadcastLinkModel, WhatsAppBroadcastGroupModel).join(
        WhatsAppBroadcastGroupModel,
        WhatsAppBroadcastGroupModel.id == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
    ).where(
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
        ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
        WhatsAppBroadcastGroupModel.agency_id == agency_id,
        WhatsAppBroadcastGroupModel.archived_at.is_(None),
        WhatsAppBroadcastGroupModel.recipient_opt_in_confirmed_at.is_not(None),
    ).order_by(WhatsAppBroadcastGroupModel.id)
    if lock:
        links = links.with_for_update().execution_options(populate_existing=True)
    broadcasts = [broadcast.id for _, broadcast in (await session.execute(links)).all()]
    if not broadcasts:
        return []
    if lock:
        # Same parent/roster lock order as document delivery. Matching below only
        # reads materialized values; edits cannot reroute a queued message.
        for model, conditions in (
            (WhatsAppBroadcastRecipientModel, (
                WhatsAppBroadcastRecipientModel.agency_id == agency_id,
                WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(broadcasts),
            )),
            (PassportSubmissionModel, (
                PassportSubmissionModel.agency_id == agency_id,
                PassportSubmissionModel.group_id == group_id,
            )),
        ):
            await session.execute(select(model).where(*conditions).order_by(model.id)
                                  .with_for_update().execution_options(populate_existing=True))
    _, recipients, submissions, matches = await load_unresolved_passport_whatsapp_match_context(
        session, group_id=group_id, agency_id=agency_id, broadcast_group_ids=broadcasts,
    )
    recipients_by_id = {row.id: row for row in recipients if row.merged_into_recipient_id is None}
    submissions_by_id = {row.id: row for row in submissions}
    recipients_by_phone: dict[str, WhatsAppBroadcastRecipientModel] = {}
    for recipient in sorted(recipients_by_id.values(), key=lambda row: (str(row.broadcast_group_id), str(row.id))):
        recipients_by_phone.setdefault(recipient.normalized_phone_number, recipient)
    contacts: dict[str, GroupUpdateContact] = {}
    for match in matches:
        sources = sorted((recipients_by_id[rid] for rid in match.recipient_ids
                          if rid in recipients_by_id),
                         key=lambda row: (str(row.broadcast_group_id), str(row.id)))
        submitted = [submissions_by_id[sid] for sid in match.submission_ids
                     if sid in submissions_by_id and has_public_collection_contact(submissions_by_id[sid])]
        ambiguous = match.status == "needs_review" or bool(match.duplicate_submission_ids)
        if submitted and not match.duplicate_submission_ids:
            for passenger in submitted:
                phone = authoritative_submission_phone(passenger)
                matched_recipient = sources[0] if sources and not ambiguous else recipients_by_phone.get(phone or "")
                key = f"submission:{passenger.id}"
                passport = (passenger.confirmed_fields or {}).get("passport_number") or (passenger.extracted_fields or {}).get("passport_number")
                contacts[key] = GroupUpdateContact(
                    audience_key=key, name=passenger.display_name or passenger.client_name,
                    recipient_id=matched_recipient.id if matched_recipient else None,
                    broadcast_group_id=matched_recipient.broadcast_group_id if matched_recipient else broadcasts[0],
                    passenger_id=passenger.id, phone_number=phone, phone_source="submitted",
                    submission_status="submitted",
                    passport_number=passport if isinstance(passport, str) else None,
                    email=passenger.client_email,
                    imported_details=dict(matched_recipient.imported_fields or {}) if matched_recipient else {},
                    reason=None if phone else "The submitted WhatsApp number needs review. No imported-number fallback is used.",
                )
        if not submitted or ambiguous:
            for recipient in sources:
                phone = normalize_whatsapp_phone(recipient.normalized_phone_number)
                key = f"recipient:{recipient.id}"
                contacts[key] = GroupUpdateContact(
                    audience_key=key, name=recipient.name or "Broadcast contact",
                    recipient_id=recipient.id, broadcast_group_id=recipient.broadcast_group_id,
                    passenger_id=match.submission_ids[0] if not ambiguous and len(match.submission_ids) == 1 else None,
                    phone_number=phone, phone_source="imported",
                    submission_status="needs_review" if ambiguous else "not_submitted",
                    imported_details=dict(recipient.imported_fields or {}),
                    reason="Review the submission match before sending." if ambiguous else
                    None if phone else "The imported WhatsApp number is invalid.",
                )
    represented_recipients = {row.recipient_id for row in contacts.values() if row.submission_status == "submitted"}
    contacts = {key: row for key, row in contacts.items()
                if row.submission_status == "submitted" or row.recipient_id not in represented_recipients}
    documents_statement = select(DistributedDocumentModel).where(
        DistributedDocumentModel.agency_id == agency_id,
        DistributedDocumentModel.group_id == group_id,
        DistributedDocumentModel.document_type == filters.document_type,
        DistributedDocumentModel.passenger_id.is_not(None),
        DistributedDocumentModel.match_status.not_in(("duplicate_document", "superseded")),
    ).order_by(DistributedDocumentModel.id)
    if lock:
        documents_statement = documents_statement.with_for_update()
    documents = list((await session.scalars(documents_statement)).all())
    by_passenger: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for document in documents:
        if document.passenger_id is not None:
            by_passenger[document.passenger_id].add(document.id)
    confirmed: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    if documents:
        result = await session.execute(select(
            DocumentWhatsAppDeliveryModel.passenger_id,
            DocumentWhatsAppDeliveryModel.distributed_document_id,
        ).where(
            DocumentWhatsAppDeliveryModel.agency_id == agency_id,
            DocumentWhatsAppDeliveryModel.group_id == group_id,
            DocumentWhatsAppDeliveryModel.document_type == filters.document_type,
            DocumentWhatsAppDeliveryModel.status.in_(ACCEPTED),
        ))
        for passenger_id, document_id in result:
            confirmed[passenger_id].add(document_id)
    rows = []
    for contact in contacts.values():
        passenger_id = contact.passenger_id
        ids = by_passenger.get(passenger_id, set()) if passenger_id is not None else set()
        confirmed_ids = confirmed.get(passenger_id, set()) if passenger_id is not None else set()
        row = replace(contact, document_count=len(ids),
                      confirmed_count=len(ids & confirmed_ids))
        if row.matches(filters):
            rows.append(row)
    return sorted(rows, key=lambda row: (row.name.casefold(), row.audience_key))
