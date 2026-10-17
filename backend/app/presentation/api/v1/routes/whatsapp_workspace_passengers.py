"""Expose only proven passenger links for a broadcast's document workspace."""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    load_unresolved_passport_whatsapp_match_context,
)
from app.presentation.api.v1.routes.whatsapp_group_visibility import staff_linked_group_filters
from app.presentation.api.v1.routes.whatsapp_history import _authorized_group
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ROLES
from app.presentation.dependencies.auth import require_role

router = APIRouter()


class BroadcastPassengerLink(BaseModel):
    group_id: UUID
    passenger_id: UUID


@router.get("/groups/{group_id}/passenger-links", response_model=list[BroadcastPassengerLink])
async def broadcast_passenger_links(
    group_id: UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[BroadcastPassengerLink]:
    broadcast = await _authorized_group(session, group_id, current_user)
    groups = await session.scalars(
        select(ClientGroupModel.id)
        .join(
            ClientGroupWhatsAppBroadcastLinkModel,
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == ClientGroupModel.id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == broadcast.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == broadcast.agency_id,
            ClientGroupModel.agency_id == broadcast.agency_id,
            ClientGroupModel.deleted_at.is_(None),
            *staff_linked_group_filters(current_user),
        )
    )
    links: set[tuple[UUID, UUID]] = set()
    for source_id in groups:
        _, _, _, matches = await load_unresolved_passport_whatsapp_match_context(
            session,
            group_id=source_id,
            agency_id=broadcast.agency_id,
        )
        for match in matches:
            if broadcast.id in match.broadcast_ids and match.status in {
                "submitted",
                "multiple_submissions",
            }:
                links.update((source_id, passenger_id) for passenger_id in match.submission_ids)
    return [
        BroadcastPassengerLink(group_id=source_id, passenger_id=passenger_id)
        for source_id, passenger_id in sorted(links, key=lambda pair: (str(pair[0]), str(pair[1])))
    ]
