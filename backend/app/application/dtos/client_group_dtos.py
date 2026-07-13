"""
Upload Link Application DTOs
=============================
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class CreateClientGroupInputDTO:
    name: str
    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    package_name: str | None = None
    departure_cities: list[str] | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ClientGroupOutputDTO:
    id: uuid.UUID
    name: str
    token: str
    agency_id: uuid.UUID
    status: str
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    closed_at: datetime | None = None
    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    package_name: str | None = None
    departure_cities: list[str] | None = None
    notes: str | None = None
    deleted_at: datetime | None = None
    deleted_passport_count: int = 0
    deletion_retained_records: bool = False


def client_group_output_from_entity(link) -> ClientGroupOutputDTO:  # type: ignore[no-untyped-def]
    return ClientGroupOutputDTO(
        id=link.id,
        name=link.name,
        token=link.token,
        agency_id=link.agency_id,
        status=link.status.value,
        created_by_user_id=link.created_by_user_id,
        created_at=link.created_at,
        closed_at=link.closed_at,
        destination=link.destination,
        travel_date=link.travel_date,
        return_date=link.return_date,
        package_name=link.package_name,
        departure_cities=link.departure_cities,
        notes=link.notes,
        deleted_at=link.deleted_at,
        deleted_passport_count=link.deleted_passport_count,
        deletion_retained_records=link.deletion_retained_records,
    )
