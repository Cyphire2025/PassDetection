"""Exact hotel source admission and locking before canonical workbook preparation."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import ArtifactError
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    RoomingAssignmentModel,
    RoomingCheckinModel,
    RoomingHotelModel,
    RoomingHotelPassengerModel,
    RoomingPassengerPreferenceModel,
    RoomingRoomModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)

MAX_ROOMING_ROWS = 1500
MAX_ROOMING_BROADCASTS = 100


def _values(row: Any) -> dict[str, Any]:
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


async def lock_rooming_export_source(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    hotel: RoomingHotelModel,
    include_priorities: bool,
) -> dict[str, Any]:
    # Caller holds exact group/hotel UPDATE locks; these fence child insertions.
    source: dict[str, Any] = {"group": _values(group), "hotel": _values(hotel)}
    fields = hotel.allocation_priority_fields or []
    if len(fields) > 6:
        raise ArtifactError("Rooming priority fields exceed the supported limit", 413)
    if include_priorities and any(
        str(field.get("key", "")).startswith("whatsapp:") for field in fields
    ):
        source.update(await _linked_priorities(session, group))
    queries = (
        (PassportSubmissionModel, PassportSubmissionModel.group_id == group.id),
        (RoomingHotelPassengerModel, RoomingHotelPassengerModel.hotel_id == hotel.id),
        (RoomingRoomModel, RoomingRoomModel.hotel_id == hotel.id),
        (RoomingAssignmentModel, RoomingAssignmentModel.hotel_id == hotel.id),
        (RoomingPassengerPreferenceModel, RoomingPassengerPreferenceModel.hotel_id == hotel.id),
        (RoomingCheckinModel, RoomingCheckinModel.hotel_id == hotel.id),
    )
    retained: dict[Any, list[Any]] = {}
    for model, condition in queries:
        rows = list(
            (
                await session.scalars(
                    select(model)
                    .where(condition)
                    .order_by(model.id)
                    .limit(MAX_ROOMING_ROWS + 1)
                    .with_for_update(read=True, nowait=True)
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        if len(rows) > MAX_ROOMING_ROWS:
            raise ArtifactError("Rooming export exceeds the source row limit", 413)
        retained[model] = rows
        source[model.__tablename__] = [_values(row) for row in rows]
    passports = {row.id: row for row in retained[PassportSubmissionModel]}
    rooms = {row.id for row in retained[RoomingRoomModel]}
    if any(row.agency_id != group.agency_id for row in passports.values()):
        raise ArtifactError("Rooming source scope is inconsistent", 409)
    for row in retained[RoomingHotelPassengerModel]:
        if row.agency_id != group.agency_id or row.group_id != group.id:
            raise ArtifactError("Rooming membership scope is inconsistent", 409)
    for model in (
        RoomingHotelPassengerModel,
        RoomingAssignmentModel,
        RoomingPassengerPreferenceModel,
        RoomingCheckinModel,
    ):
        for row in retained[model]:
            if row.passenger_id not in passports:
                raise ArtifactError("Rooming passenger association is unavailable", 409)
            if hasattr(row, "room_id") and row.room_id not in rooms:
                raise ArtifactError("Rooming room association is unavailable", 409)
            if model is RoomingCheckinModel and row.agency_id != group.agency_id:
                raise ArtifactError("Check-in scope is inconsistent", 409)
    return source


async def _linked_priorities(session: AsyncSession, group: ClientGroupModel) -> dict[str, Any]:
    query = (
        select(ClientGroupWhatsAppBroadcastLinkModel)
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
        )
        .order_by(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id)
        .limit(MAX_ROOMING_BROADCASTS + 1)
    )
    identifiers = [row.broadcast_group_id for row in (await session.scalars(query)).all()]
    if len(identifiers) > MAX_ROOMING_BROADCASTS:
        raise ArtifactError("Rooming export exceeds the linked broadcast limit", 413)
    broadcasts = list(
        (
            await session.scalars(
                select(WhatsAppBroadcastGroupModel)
                .where(
                    WhatsAppBroadcastGroupModel.id.in_(identifiers),
                    WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
                )
                .order_by(WhatsAppBroadcastGroupModel.id)
                .with_for_update(nowait=True)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if {row.id for row in broadcasts} != set(identifiers):
        raise ArtifactError("Rooming linked source is unavailable", 409)
    links = (
        await session.scalars(
            query.with_for_update(read=True, nowait=True).execution_options(populate_existing=True)
        )
    ).all()
    recipients = (
        await session.scalars(
            select(WhatsAppBroadcastRecipientModel)
            .where(
                WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(identifiers),
                WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            )
            .order_by(WhatsAppBroadcastRecipientModel.id)
            .limit(MAX_ROOMING_ROWS + 1)
            .with_for_update(read=True, nowait=True)
            .execution_options(populate_existing=True)
        )
    ).all()
    if len(recipients) > MAX_ROOMING_ROWS:
        raise ArtifactError("Rooming export exceeds the linked recipient limit", 413)
    return {
        "broadcasts": [_values(row) for row in broadcasts],
        "links": [_values(row) for row in links],
        "recipients": [_values(row) for row in recipients],
    }
