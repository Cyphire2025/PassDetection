"""Flush-only hotel creation shared with the website; no room or roster effects."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import RoomingHotelModel


class HotelCreationFields(Protocol):
    hotel_name: str
    city: str | None
    check_in_date: date | None
    check_out_date: date | None


async def create_hotel(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    actor_id: uuid.UUID,
    body: HotelCreationFields,
) -> RoomingHotelModel:
    hotel = RoomingHotelModel(
        agency_id=agency_id,
        group_id=group_id,
        hotel_name=body.hotel_name.strip(),
        city=body.city.strip() if body.city else None,
        check_in_date=body.check_in_date,
        check_out_date=body.check_out_date,
        created_by_user_id=actor_id,
    )
    session.add(hotel)
    await session.flush()
    return hotel
