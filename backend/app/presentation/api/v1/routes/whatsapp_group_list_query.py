"""Correlated group counts without recipient or source fanout."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect

from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSourceContactModel,
)


def broadcast_group_count_projections() -> tuple[ScalarSelect[int], ColumnElement[bool], ScalarSelect[int]]:
    rejected_contact_count = (
        select(func.count(WhatsAppBroadcastRejectedContactModel.id))
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id
            == WhatsAppBroadcastGroupModel.id,
        )
        .correlate(WhatsAppBroadcastGroupModel)
        .scalar_subquery()
    )
    import_only_source = select(ClientGroupWhatsAppBroadcastLinkModel.id).join(
        ClientGroupModel,
        ClientGroupModel.id == ClientGroupWhatsAppBroadcastLinkModel.client_group_id,
    ).where(
        ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == WhatsAppBroadcastGroupModel.id,
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == WhatsAppBroadcastGroupModel.agency_id,
        ClientGroupModel.agency_id == WhatsAppBroadcastGroupModel.agency_id,
        ClientGroupModel.import_only.is_(True),
        ClientGroupModel.deleted_at.is_(None),
    ).exists()
    source_contact_count = select(func.count(WhatsAppBroadcastSourceContactModel.id)).where(
        WhatsAppBroadcastSourceContactModel.broadcast_group_id == WhatsAppBroadcastGroupModel.id,
        WhatsAppBroadcastSourceContactModel.agency_id == WhatsAppBroadcastGroupModel.agency_id,
    ).correlate(WhatsAppBroadcastGroupModel).scalar_subquery()
    return rejected_contact_count, import_only_source, source_contact_count
