"""Document distribution: matching."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import (
    compare_group_submissions,
)
from app.application.use_cases.whatsapp.private_delivery_identity import (
    is_private_delivery_match,
)
from app.domain.entities.entities import PassportSubmission
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.documents.document_matcher import (
    MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER,
    MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST,
    DocumentMatcher,
    PassengerIdentifier,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    matching_field_keys_from_storage,
    recipient_comparison_from_model,
    submission_comparison_from_model,
)
from app.presentation.api.v1.routes.document_distribution_match_policy import (
    source_matching_fields_by_broadcast as _source_matching_fields_by_broadcast,
)
from app.presentation.api.v1.routes.document_distribution_match_policy import (
    source_with_matching_fields as _source_with_matching_fields,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _linked_document_match_source_from_models,
    _LinkedDocumentMatchSource,
)


async def _linked_whatsapp_recipients(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    require_opt_in: bool = True,
) -> tuple[
    dict[uuid.UUID, str],
    dict[uuid.UUID, tuple[str, ...] | None],
    list[WhatsAppBroadcastRecipientModel],
]:
    filters = [
        ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
        WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
    ]
    if require_opt_in:
        filters.append(WhatsAppBroadcastGroupModel.recipient_opt_in_confirmed_at.is_not(None))
    linked_result = await session.execute(
        select(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            WhatsAppBroadcastGroupModel.name,
            ClientGroupWhatsAppBroadcastLinkModel.matching_field_keys,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id
            == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
        )
        .where(*filters)
    )
    linked_rows = linked_result.all()
    linked_broadcasts = {
        broadcast_id: broadcast_name
        for broadcast_id, broadcast_name, _matching_fields in linked_rows
    }
    matching_fields_by_broadcast = {
        broadcast_id: matching_field_keys_from_storage(matching_fields)
        for broadcast_id, _broadcast_name, matching_fields in linked_rows
    }
    if not linked_broadcasts:
        return {}, {}, []
    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(list(linked_broadcasts)),
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
        )
    )
    return (
        linked_broadcasts,
        matching_fields_by_broadcast,
        list(recipient_result.scalars().all()),
    )


async def _read_linked_document_match_source(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    lock: bool,
) -> _LinkedDocumentMatchSource:
    """Read matching evidence coherently, optionally under stable write locks.

    The locked path is called only after the client-group row is locked.  It
    then follows the shared order group -> broadcasts -> links -> recipients;
    the caller locks passengers last.  Parent locks also serialize child-row
    inserts through their foreign keys, preventing recipient/link phantoms.
    """

    if not lock:
        result = await session.execute(
            select(
                ClientGroupWhatsAppBroadcastLinkModel,
                WhatsAppBroadcastGroupModel,
                WhatsAppBroadcastRecipientModel,
            )
            .select_from(ClientGroupWhatsAppBroadcastLinkModel)
            .join(
                WhatsAppBroadcastGroupModel,
                WhatsAppBroadcastGroupModel.id
                == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            )
            .outerjoin(
                WhatsAppBroadcastRecipientModel,
                and_(
                    WhatsAppBroadcastRecipientModel.broadcast_group_id
                    == WhatsAppBroadcastGroupModel.id,
                    WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                    WhatsAppBroadcastRecipientModel.removed_at.is_(None),
                ),
            )
            .where(
                ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
                ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
                WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
            )
            .order_by(
                WhatsAppBroadcastGroupModel.id,
                ClientGroupWhatsAppBroadcastLinkModel.id,
                WhatsAppBroadcastRecipientModel.id,
            )
        )
        links_by_id: dict[uuid.UUID, ClientGroupWhatsAppBroadcastLinkModel] = {}
        broadcasts_by_id: dict[uuid.UUID, WhatsAppBroadcastGroupModel] = {}
        recipients_by_id: dict[uuid.UUID, WhatsAppBroadcastRecipientModel] = {}
        for link, broadcast, recipient in result.all():
            links_by_id[link.id] = link
            broadcasts_by_id[broadcast.id] = broadcast
            if recipient is not None:
                recipients_by_id[recipient.id] = recipient
        links = list(links_by_id.values())
        return _source_with_matching_fields(
            _linked_document_match_source_from_models(
                group=group,
                links=links,
                broadcasts=list(broadcasts_by_id.values()),
                recipients=list(recipients_by_id.values()),
            ),
            links,
        )

    linked_id_result = await session.execute(
        select(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id)
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
        )
        .order_by(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id)
    )
    linked_ids = sorted(set(linked_id_result.scalars().all()), key=str)
    broadcasts: list[WhatsAppBroadcastGroupModel] = []
    if linked_ids:
        broadcast_result = await session.execute(
            select(WhatsAppBroadcastGroupModel)
            .where(
                WhatsAppBroadcastGroupModel.id.in_(linked_ids),
                WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
            )
            .order_by(WhatsAppBroadcastGroupModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        broadcasts = list(broadcast_result.scalars().all())
        if {broadcast.id for broadcast in broadcasts} != set(linked_ids):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "A linked WhatsApp list changed while the PDFs were being "
                    "processed. Review and upload them again."
                ),
            )

    link_result = await session.execute(
        select(ClientGroupWhatsAppBroadcastLinkModel)
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
        )
        .order_by(ClientGroupWhatsAppBroadcastLinkModel.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    links = list(link_result.scalars().all())
    if {link.broadcast_group_id for link in links} != set(linked_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The linked WhatsApp lists changed while the PDFs were being "
                "processed. Review and upload them again."
            ),
        )

    recipients: list[WhatsAppBroadcastRecipientModel] = []
    if linked_ids:
        recipient_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel)
            .where(
                WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(linked_ids),
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            )
            .order_by(WhatsAppBroadcastRecipientModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        recipients = list(recipient_result.scalars().all())
    return _source_with_matching_fields(
        _linked_document_match_source_from_models(
            group=group,
            links=links,
            broadcasts=broadcasts,
            recipients=recipients,
        ),
        links,
    )


async def _linked_document_match_identifiers(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    passengers: list[PassportSubmission],
    matcher: DocumentMatcher,
    source: _LinkedDocumentMatchSource | None = None,
) -> tuple[PassengerIdentifier, ...]:
    """Attach linked WhatsApp-Excel codes only after an unambiguous roster match."""

    if source is None:
        (
            linked_broadcasts,
            matching_fields_by_broadcast,
            recipients,
        ) = await _linked_whatsapp_recipients(
            session,
            group=group,
            require_opt_in=False,
        )
    else:
        linked_broadcasts = source.linked_broadcasts
        matching_fields_by_broadcast = _source_matching_fields_by_broadcast(source)
        recipients = list(source.recipients)
    scoped_recipients = [
        recipient
        for recipient in recipients
        if recipient.agency_id == group.agency_id
        and recipient.broadcast_group_id in linked_broadcasts
    ]
    scoped_passengers = [
        passenger
        for passenger in passengers
        if passenger.agency_id == group.agency_id and passenger.group_id == group.id
    ]
    if not scoped_recipients or not scoped_passengers:
        return ()
    comparison_recipients = [
        recipient_comparison_from_model(
            recipient,
            linked_broadcasts,
            matching_fields_by_broadcast,
        )
        for recipient in scoped_recipients
    ]
    comparison_submissions = [
        submission_comparison_from_model(passenger)
        for passenger in scoped_passengers
    ]
    rows, _ = await asyncio.to_thread(
        compare_group_submissions,
        comparison_recipients,
        comparison_submissions,
    )
    identifiers: list[PassengerIdentifier] = []
    identifiers_seen: set[tuple[uuid.UUID, str, str]] = set()
    identifiers_per_passenger: dict[uuid.UUID, int] = {}
    matched_rows = sorted(
        (row for row in rows if is_private_delivery_match(row)),
        key=lambda row: (str(row.submission_ids[0]), tuple(map(str, row.recipient_ids))),
    )
    for row in matched_rows:
        if len(identifiers) >= MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST:
            break
        passenger_id = row.submission_ids[0]
        for field_set in sorted(row.recipient_fields, key=lambda item: str(item.recipient_id)):
            if (
                len(identifiers) >= MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST
                or identifiers_per_passenger.get(passenger_id, 0)
                >= MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER
            ):
                break
            aliases = sorted(
                matcher.stored_identifier_aliases(field_set.fields),
                key=lambda item: (item[1], item[0]),
            )
            for value, kind in aliases:
                if (
                    len(identifiers) >= MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST
                    or identifiers_per_passenger.get(passenger_id, 0)
                    >= MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER
                ):
                    break
                identity = (passenger_id, kind, value)
                if identity in identifiers_seen:
                    continue
                identifiers_seen.add(identity)
                identifiers.append(
                    PassengerIdentifier(
                        passenger_id=passenger_id,
                        agency_id=group.agency_id,
                        group_id=group.id,
                        kind=kind,
                        value=value,
                        source="linked WhatsApp Excel",
                    )
                )
                identifiers_per_passenger[passenger_id] = (
                    identifiers_per_passenger.get(passenger_id, 0) + 1
                )
    return tuple(identifiers)
