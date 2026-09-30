"""Named bounded WhatsApp projections; no route handlers or mutation helpers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.whatsapp_delivery_status import (
    WHATSAPP_IN_PROGRESS_STATUSES,
    WHATSAPP_READ_STATUS_KEYS,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSourceContactModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
)


def _page(statement: Any, model: Any, cutoff: datetime,
          after: tuple[datetime, uuid.UUID] | None, size: int) -> Any:
    statement = statement.where(model.created_at <= cutoff)
    if after:
        statement = statement.where(or_(model.created_at < after[0],
                                        and_(model.created_at == after[0], model.id < after[1])))
    return statement.order_by(model.created_at.desc(), model.id.desc()).limit(size + 1)


class MCPWhatsAppReadRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def broadcasts(self, *, agency_id: uuid.UUID | None, group_id: uuid.UUID | None,
                         name: str | None, include_archived: bool, cutoff: datetime,
                         after: tuple[datetime, uuid.UUID] | None, size: int) -> list[dict[str, Any]]:
        group, link = WhatsAppBroadcastGroupModel, ClientGroupWhatsAppBroadcastLinkModel
        counts = []
        for model, label in ((WhatsAppBroadcastRecipientModel, "active_recipient_entries"),
                             (WhatsAppBroadcastSourceContactModel, "source_traveller_rows"),
                             (WhatsAppBroadcastRejectedContactModel, "rejected_contact_rows")):
            count = select(func.count(model.id)).where(model.broadcast_group_id == group.id, model.agency_id == group.agency_id)
            if model is WhatsAppBroadcastRecipientModel:
                count = count.where(model.removed_at.is_(None))
            counts.append(count.correlate(group).scalar_subquery().label(label))
        linked = select(link.id).join(ClientGroupModel, ClientGroupModel.id == link.client_group_id).where(
            link.broadcast_group_id == group.id, link.agency_id == group.agency_id,
            ClientGroupModel.agency_id == group.agency_id, ClientGroupModel.deleted_at.is_(None))
        import_only = linked.where(ClientGroupModel.import_only.is_(True)).exists()
        statement = select(group.id, group.name, group.agency_id, AgencyModel.name.label("agency_name"),
                           group.archived_at, group.recipient_opt_in_confirmed_at, group.created_at,
                           group.updated_at, import_only.label("has_import_only_source"), *counts).join(AgencyModel, AgencyModel.id == group.agency_id)
        if group_id is not None:
            statement = statement.where(linked.where(link.client_group_id == group_id).exists())
        if agency_id is not None:
            statement = statement.where(group.agency_id == agency_id)
        if name is not None:
            statement = statement.where(group.name.icontains(name, autoescape=True))
        if not include_archived:
            statement = statement.where(group.archived_at.is_(None))
        result = await self.session.execute(_page(statement, group, cutoff, after, size))
        return [dict(row) for row in result.mappings()]

    async def broadcast(self, broadcast_id: uuid.UUID, agency_id: uuid.UUID | None) -> dict[str, Any] | None:
        model = WhatsAppBroadcastGroupModel
        statement = select(model.id, model.agency_id, model.name, model.archived_at).where(model.id == broadcast_id)
        if agency_id is not None:
            statement = statement.where(model.agency_id == agency_id)
        row = (await self.session.execute(statement)).mappings().one_or_none()
        return dict(row) if row else None

    async def audience(self, *, broadcast_id: uuid.UUID, agency_id: uuid.UUID, kind: str,
                       include_contact_details: bool, include_removed: bool, cutoff: datetime,
                       after: tuple[datetime, uuid.UUID] | None, size: int) -> list[dict[str, Any]]:
        if kind == "recipients":
            recipient = WhatsAppBroadcastRecipientModel
            fields: list[Any] = [recipient.id, recipient.created_at, recipient.name, recipient.is_source_managed,
                                recipient.removed_at, recipient.merged_into_recipient_id, recipient.suppressed_by_roster_resolution_id]
            if include_contact_details:
                fields.append(recipient.normalized_phone_number)
            model: Any = recipient
        elif kind == "source_contacts":
            source = WhatsAppBroadcastSourceContactModel
            fields = [source.id, source.created_at, func.substr(source.name, 1, 255).label("name"),
                      source.source_group_id, source.source_submission_id, source.recipient_id, source.issue]
            if include_contact_details:
                fields.extend([source.normalized_phone_number, func.substr(source.raw_phone_number, 1, 64).label("raw_phone_number")])
            model = source
        elif kind == "support_contacts":
            support = WhatsAppBroadcastSupportContactModel
            fields = [support.id, support.created_at, support.name, support.sort_order]
            if include_contact_details:
                fields.append(support.normalized_phone_number)
            model = support
        else:
            rejected = WhatsAppBroadcastRejectedContactModel
            fields = [rejected.id, rejected.created_at, rejected.raw_name.label("name"), rejected.reason_code, rejected.row_number]
            if include_contact_details:
                fields.append(rejected.raw_phone_number)
            model = rejected
        statement = select(*fields).where(model.broadcast_group_id == broadcast_id, model.agency_id == agency_id)
        if kind == "recipients" and not include_removed:
            statement = statement.where(model.removed_at.is_(None))
        result = await self.session.execute(_page(statement, model, cutoff, after, size))
        return [dict(row) for row in result.mappings()]

    async def batch(self, *, batch_id: uuid.UUID, broadcast_id: uuid.UUID, agency_id: uuid.UUID,
                    cutoff: datetime, stale_cutoff: datetime, after: tuple[datetime, uuid.UUID] | None,
                    size: int, include_contact_details: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        model = WhatsAppMessageLogModel
        scope = (model.batch_id == batch_id, model.broadcast_group_id == broadcast_id,
                 model.agency_id == agency_id, model.created_at <= cutoff)
        stored = case((model.status.in_(WHATSAPP_READ_STATUS_KEYS), model.status), else_="unrecognized")
        effective = case((and_(model.status.in_(WHATSAPP_IN_PROGRESS_STATUSES), model.status_updated_at < stale_cutoff), "stalled"), else_=stored)
        summary = await self.session.execute(select(stored.label("stored_status"), effective.label("effective_status"), func.count().label("count")).where(*scope).group_by(stored, effective))
        fields = [model.id, model.recipient_id, model.created_at, model.message_type,
                  model.status, effective.label("effective_status"), model.status_updated_at,
                  model.provider_status_at, model.error_message.is_not(None).label("has_error")]
        if include_contact_details:
            fields.append(model.normalized_phone_number)
        result = await self.session.execute(_page(select(*fields).where(*scope), model, cutoff, after, size))
        return [dict(row) for row in result.mappings()], [dict(row) for row in summary.mappings()]
