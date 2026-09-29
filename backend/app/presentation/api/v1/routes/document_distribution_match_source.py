"""Coherent, optionally bounded document matching source snapshots and locks."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.presentation.api.v1.routes.document_distribution_match_policy import (
    source_with_matching_fields as _source_with_matching_fields,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _linked_document_match_source_from_models,
    _LinkedDocumentMatchSource,
)

__all__ = ["_read_linked_document_match_source", "_source_with_matching_fields"]


async def _read_linked_document_match_source(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    lock: bool,
    max_source_rows: int | None = None,
) -> _LinkedDocumentMatchSource:
    """Read matching evidence coherently, optionally under stable write locks.

    The locked path is called only after the client-group row is locked.  It
    then follows the shared order group -> broadcasts -> links -> recipients;
    the caller locks passengers last.  Parent locks also serialize child-row
    inserts through their foreign keys, preventing recipient/link phantoms.
    """

    def require_bounded(rows: Sequence[object]) -> None:
        if max_source_rows is not None and len(rows) > max_source_rows:
            raise HTTPException(
                status_code=413,
                detail="Linked document matching evidence exceeds the request limit",
            )

    source_limit = max_source_rows + 1 if max_source_rows is not None else None
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
            .limit(source_limit)
            .execution_options(populate_existing=True)
        )
        links_by_id: dict[uuid.UUID, ClientGroupWhatsAppBroadcastLinkModel] = {}
        broadcasts_by_id: dict[uuid.UUID, WhatsAppBroadcastGroupModel] = {}
        recipients_by_id: dict[uuid.UUID, WhatsAppBroadcastRecipientModel] = {}
        rows = list(result.all())
        require_bounded(rows)
        for link, broadcast, recipient in rows:
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
        .limit(source_limit)
    )
    linked_ids = sorted(set(linked_id_result.scalars().all()), key=str)
    require_bounded(linked_ids)
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
        .limit(source_limit)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    links = list(link_result.scalars().all())
    require_bounded(links)
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
            .limit(source_limit)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        recipients = list(recipient_result.scalars().all())
        require_bounded(recipients)
    return _source_with_matching_fields(
        _linked_document_match_source_from_models(
            group=group,
            links=links,
            broadcasts=broadcasts,
            recipients=recipients,
        ),
        links,
    )
