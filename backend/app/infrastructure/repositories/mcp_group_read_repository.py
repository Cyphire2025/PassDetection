"""Bounded, tenant-consistent group projections for the MCP application service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES, User
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member


class MCPGroupReadRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def page(
        self, *, user: User, created_before: datetime,
        after: tuple[datetime, uuid.UUID] | None, page_size: int,
        name: str | None, name_match: str, agency_id: uuid.UUID | None,
        group_id: uuid.UUID | None, status: str | None, include_deleted: bool,
    ) -> list[dict[str, Any]]:
        group, passport = ClientGroupModel, PassportSubmissionModel
        link, broadcast = ClientGroupWhatsAppBroadcastLinkModel, WhatsAppBroadcastGroupModel
        recipient = WhatsAppBroadcastRecipientModel
        passport_scope = (passport.group_id == group.id, passport.agency_id == group.agency_id)
        passport_count = select(func.count(passport.id)).where(*passport_scope).correlate(group).scalar_subquery()
        operational_count = select(func.count(passport.id)).where(
            *passport_scope, passport.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
            operational_roster_member(),
        ).correlate(group).scalar_subquery()
        link_scope = (link.client_group_id == group.id, link.agency_id == group.agency_id,
                      broadcast.agency_id == group.agency_id)
        linked_count = select(func.count(link.id)).join(
            broadcast, broadcast.id == link.broadcast_group_id,
        ).where(*link_scope).correlate(group).scalar_subquery()
        recipient_count = select(func.count(recipient.id)).select_from(link).join(
            broadcast, broadcast.id == link.broadcast_group_id,
        ).join(recipient, and_(recipient.broadcast_group_id == broadcast.id,
                              recipient.agency_id == group.agency_id)).where(
            *link_scope, broadcast.archived_at.is_(None), recipient.removed_at.is_(None),
        ).correlate(group).scalar_subquery()

        statement = select(
            group.id, group.name, group.agency_id, AgencyModel.name.label("agency_name"),
            group.status, group.import_only, group.created_at, group.destination,
            group.travel_date, group.return_date, group.timezone, group.roster_revision,
            group.deleted_at, passport_count.label("passport_submission_records"),
            operational_count.label("operational_passengers"),
            linked_count.label("linked_whatsapp_broadcasts"),
            recipient_count.label("whatsapp_active_recipient_entries"),
        ).join(AgencyModel, AgencyModel.id == group.agency_id).where(group.created_at <= created_before)
        statement = AuthorizationPolicy.apply_group_visibility_scope(statement, user)
        if not include_deleted:
            statement = statement.where(group.deleted_at.is_(None), group.status != "deleted")
        if agency_id is not None:
            statement = statement.where(group.agency_id == agency_id)
        if group_id is not None:
            statement = statement.where(group.id == group_id)
        if status is not None:
            statement = statement.where(group.status == status)
        if name is not None:
            if name_match == "exact":
                escaped = name.replace("/", "//").replace("%", "/%").replace("_", "/_")
                statement = statement.where(group.name.ilike(escaped, escape="/"))
            else:
                statement = statement.where(group.name.icontains(name, autoescape=True))
        if after is not None:
            created_at, identifier = after
            statement = statement.where(or_(group.created_at < created_at,
                                            and_(group.created_at == created_at, group.id < identifier)))
        rows = await self.session.execute(statement.order_by(group.created_at.desc(), group.id.desc()).limit(page_size + 1))
        return [dict(row) for row in rows.mappings()]
