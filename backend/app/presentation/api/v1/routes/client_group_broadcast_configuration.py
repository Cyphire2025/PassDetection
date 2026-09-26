"""Broadcast link reads and matching-field configuration."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    matching_field_keys_from_storage,
)
from app.presentation.api.v1.routes.whatsapp_contact_support import _matching_field_options
from app.presentation.api.v1.schemas.client_group_schemas import WhatsAppBroadcastSummaryResponse


async def _broadcast_summaries(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    broadcast_ids: list[uuid.UUID] | None = None,
    existing_group_id: uuid.UUID | None = None,
    allowed_archived_ids: list[uuid.UUID] | None = None,
) -> list[WhatsAppBroadcastSummaryResponse]:
    stmt = (
        select(
            WhatsAppBroadcastGroupModel,
            func.count(WhatsAppBroadcastRecipientModel.id).label("recipient_count"),
        )
        .outerjoin(
            WhatsAppBroadcastRecipientModel,
            and_(
                WhatsAppBroadcastRecipientModel.broadcast_group_id
                == WhatsAppBroadcastGroupModel.id,
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            ),
        )
        .where(WhatsAppBroadcastGroupModel.agency_id == agency_id)
    )
    active_or_retained = [WhatsAppBroadcastGroupModel.archived_at.is_(None)]
    if existing_group_id is not None:
        active_or_retained.append(WhatsAppBroadcastGroupModel.id.in_(
            select(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id).where(
                ClientGroupWhatsAppBroadcastLinkModel.client_group_id == existing_group_id,
                ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            )
        ))
    if allowed_archived_ids:
        active_or_retained.append(WhatsAppBroadcastGroupModel.id.in_(allowed_archived_ids))
    stmt = stmt.where(or_(*active_or_retained))
    if broadcast_ids is not None:
        if not broadcast_ids:
            return []
        stmt = stmt.where(WhatsAppBroadcastGroupModel.id.in_(broadcast_ids))
    result = await session.execute(
        stmt.group_by(WhatsAppBroadcastGroupModel.id).order_by(
            func.lower(WhatsAppBroadcastGroupModel.name).asc(),
            WhatsAppBroadcastGroupModel.id.asc(),
        )
    )
    return [
        WhatsAppBroadcastSummaryResponse(
            id=broadcast.id,
            name=broadcast.name,
            archived_at=broadcast.archived_at,
            recipient_count=int(recipient_count or 0),
            available_matching_fields=_matching_field_options(
                getattr(broadcast, "imported_field_keys", [])
            ),
            created_at=broadcast.created_at,
            updated_at=broadcast.updated_at,
        )
        for broadcast, recipient_count in result.all()
    ]


async def _linked_broadcast_summaries_by_group(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    client_group_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[WhatsAppBroadcastSummaryResponse]]:
    if not client_group_ids:
        return {}
    result = await session.execute(
        select(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id,
            ClientGroupWhatsAppBroadcastLinkModel.matching_field_keys,
            WhatsAppBroadcastGroupModel,
            func.count(WhatsAppBroadcastRecipientModel.id).label("recipient_count"),
        )
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
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            ),
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id.in_(client_group_ids),
        )
        .group_by(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id,
            ClientGroupWhatsAppBroadcastLinkModel.matching_field_keys,
            WhatsAppBroadcastGroupModel.id,
        )
        .order_by(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id.asc(),
            func.lower(WhatsAppBroadcastGroupModel.name).asc(),
            WhatsAppBroadcastGroupModel.id.asc(),
        )
    )
    summaries: dict[uuid.UUID, list[WhatsAppBroadcastSummaryResponse]] = {
        group_id: [] for group_id in client_group_ids
    }
    for group_id, matching_field_keys, broadcast, recipient_count in result.all():
        decoded_matching_fields = matching_field_keys_from_storage(matching_field_keys)
        summaries.setdefault(group_id, []).append(
            WhatsAppBroadcastSummaryResponse(
                id=broadcast.id,
                name=broadcast.name,
                archived_at=broadcast.archived_at,
                recipient_count=int(recipient_count or 0),
                available_matching_fields=_matching_field_options(
                    getattr(broadcast, "imported_field_keys", [])
                ),
                matching_field_keys=(
                    list(decoded_matching_fields) if decoded_matching_fields is not None else None
                ),
                created_at=broadcast.created_at,
                updated_at=broadcast.updated_at,
            )
        )
    return summaries


def requested_link_configuration(
    summaries: list[WhatsAppBroadcastSummaryResponse], requested_ids: list[uuid.UUID],
    previous_configuration: dict[uuid.UUID, tuple[str, ...] | None],
    matching_fields_by_broadcast: dict[uuid.UUID, list[str]] | None,
) -> dict[uuid.UUID, tuple[str, ...] | None]:
    requested_configuration: dict[uuid.UUID, tuple[str, ...] | None] = {}
    supplied_configuration = matching_fields_by_broadcast or {}
    available_by_broadcast = {
        summary.id: {field.key for field in getattr(summary, "available_matching_fields", [])}
        for summary in summaries
    }
    for broadcast_id in requested_ids:
        if broadcast_id in supplied_configuration:
            selected = tuple(dict.fromkeys(supplied_configuration[broadcast_id]))
            unavailable = sorted(set(selected) - available_by_broadcast.get(broadcast_id, set()))
            if unavailable:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "One or more selected matching fields are not available "
                        "in the WhatsApp broadcast: " + ", ".join(unavailable)
                    ),
                )
            requested_configuration[broadcast_id] = selected
        else:
            requested_configuration[broadcast_id] = previous_configuration.get(broadcast_id)
    return requested_configuration


def summaries_with_matching_fields(
    summaries: list[WhatsAppBroadcastSummaryResponse],
    requested_configuration: dict[uuid.UUID, tuple[str, ...] | None],
) -> list[WhatsAppBroadcastSummaryResponse]:
    summaries = [
        (
            summary.model_copy(
                update={
                    "matching_field_keys": (
                        list(requested_configuration[summary.id] or ())
                        if requested_configuration[summary.id] is not None
                        else None
                    )
                }
            )
            if hasattr(summary, "model_copy")
            else summary
        )
        for summary in summaries
    ]
    return summaries
