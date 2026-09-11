"""Authoritative submitted destinations for approved travellers' documents."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.domain.entities.entities import OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.repositories.operational_roster import operational_roster_member


@dataclass(frozen=True, slots=True)
class TravellerDestination:
    passenger_id: uuid.UUID
    passenger_name: str
    phone_number: str | None
    reason: str | None = None


async def load_traveller_destinations(
    session: AsyncSession, *, agency_id: uuid.UUID, group_id: uuid.UUID, lock: bool = False,
) -> list[TravellerDestination]:
    """Use each passenger's own entered number, including intentional shared numbers.

    Employee codes identify the qualifying record; they do not identify a
    document destination. A missing traveller phone must be corrected explicitly.
    """
    statement = select(PassportSubmissionModel).join(
        ClientGroupModel, ClientGroupModel.id == PassportSubmissionModel.group_id,
    ).where(
        PassportSubmissionModel.agency_id == agency_id,
        PassportSubmissionModel.group_id == group_id,
        ClientGroupModel.agency_id == agency_id,
        ClientGroupModel.deleted_at.is_(None),
        ClientGroupModel.status.not_in(("archived", "deleted")),
        PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
        operational_roster_member(),
    ).order_by(PassportSubmissionModel.id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    passengers = (await session.scalars(statement)).all()
    destinations: list[TravellerDestination] = []
    for passenger in passengers:
        phone = normalize_whatsapp_phone(passenger.client_phone)
        destinations.append(TravellerDestination(
            passenger_id=passenger.id,
            passenger_name=passenger.client_name,
            phone_number=phone,
            reason=None if phone else (
                "Add a valid WhatsApp number in this traveller's submitted details "
                "before sending their welcome or documents."
            ),
        ))
    return destinations
