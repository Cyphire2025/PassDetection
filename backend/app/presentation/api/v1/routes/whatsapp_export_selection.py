"""Resolve exportable group scope and exact requested roster identities."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
)
from app.presentation.api.v1.routes.whatsapp_export_support import (
    _exportable_links,
    _roster_identity,
    _stale_rows,
)
from app.presentation.api.v1.routes.whatsapp_recipient_roster import get_broadcast_recipient_roster
from app.presentation.api.v1.schemas.whatsapp_export_schemas import WhatsAppFilterExportRequest
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppRecipientRosterItemResponse


@dataclass(frozen=True)
class ExportSelection:
    """Current export policy results and the exact requested delivery identities."""

    links: list[tuple[ClientGroupModel, ClientGroupWhatsAppBroadcastLinkModel]]
    groups: dict[uuid.UUID, ClientGroupModel]
    source_visible_ids: set[uuid.UUID]
    roster_by_id: dict[tuple[str, uuid.UUID], WhatsAppRecipientRosterItemResponse]
    selected_recipient_ids: set[uuid.UUID]


async def select_export_rows(
    body: WhatsAppFilterExportRequest,
    broadcast: WhatsAppBroadcastGroupModel,
    user: User,
    session: AsyncSession,
) -> ExportSelection:
    links = await _exportable_links(session, broadcast, user)
    groups = {group.id: group for group, _link in links}
    source_visible_ids = {
        group.id
        for group, link in links
        if group.status == "active" and (group.import_only or link.sync_contacts_from_group)
    }
    roster_by_id: dict[tuple[str, uuid.UUID], WhatsAppRecipientRosterItemResponse] = {}
    selected_recipient_ids: set[uuid.UUID] = set()
    if body.view == "delivery":
        roster = await get_broadcast_recipient_roster(broadcast.id, user, session)
        roster_by_id = {_roster_identity(row): row for row in roster.items}
        if any((item.kind, item.id) not in roster_by_id for item in body.items):
            raise _stale_rows()
        selected_recipient_ids = {
            item.id for item in body.items if item.kind in {"recipient", "replaced"}
        }
    return ExportSelection(links, groups, source_visible_ids, roster_by_id, selected_recipient_ids)
