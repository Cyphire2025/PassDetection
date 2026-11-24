"""Read approved passengers, latest QR versions and existing delivery receipts."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import (
    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassengerQRTokenModel,
    PassengerQrWhatsAppDeliveryModel,
    PassportSubmissionModel,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member


async def load_qr_preview_sources(
    session: AsyncSession, *, group: ClientGroupModel
) -> tuple[
    list[PassportSubmissionModel],
    dict[uuid.UUID, PassengerQRTokenModel],
    dict[uuid.UUID, PassengerQrWhatsAppDeliveryModel],
]:
    passengers_result = await session.execute(
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
            operational_roster_member(),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )
    passengers = list(passengers_result.scalars().all())
    passenger_ids = [passenger.id for passenger in passengers]
    latest_token_by_passenger: dict[uuid.UUID, PassengerQRTokenModel] = {}
    if passenger_ids:
        token_result = await session.execute(
            select(PassengerQRTokenModel)
            .where(PassengerQRTokenModel.passenger_id.in_(passenger_ids))
            .order_by(
                PassengerQRTokenModel.passenger_id,
                PassengerQRTokenModel.token_version.desc(),
                PassengerQRTokenModel.created_at.desc(),
            )
        )
        for qr_token in token_result.scalars().all():
            latest_token_by_passenger.setdefault(qr_token.passenger_id, qr_token)
    token_ids = [token.id for token in latest_token_by_passenger.values()]
    delivery_by_token: dict[uuid.UUID, PassengerQrWhatsAppDeliveryModel] = {}
    if token_ids:
        delivery_result = await session.execute(
            select(PassengerQrWhatsAppDeliveryModel).where(
                PassengerQrWhatsAppDeliveryModel.qr_token_id.in_(token_ids)
            )
        )
        delivery_by_token = {
            delivery.qr_token_id: delivery for delivery in delivery_result.scalars().all()
        }
    return (passengers, latest_token_by_passenger, delivery_by_token)
