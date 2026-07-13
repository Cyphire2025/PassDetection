"""
Upload Link Presentation Schemas
================================
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator


def _normalize_departure_cities(values: list[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    cities: list[str] = []
    for value in values:
        city = " ".join(str(value).strip().split())
        if not city:
            continue
        key = city.casefold()
        if key in seen:
            continue
        seen.add(key)
        cities.append(city[:120])
    return cities


class CreateClientGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    destination: str | None = Field(default=None, max_length=255)
    travel_date: date | None = None
    return_date: date | None = None
    package_name: str | None = Field(default=None, max_length=255)
    departure_cities: list[str] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("departure_cities", mode="before")
    @classmethod
    def normalize_departure_cities(cls, value: list[str] | None) -> list[str]:
        return _normalize_departure_cities(value)


class UpdateClientGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    destination: str | None = Field(default=None, max_length=255)
    travel_date: date | None = None
    return_date: date | None = None
    package_name: str | None = Field(default=None, max_length=255)
    departure_cities: list[str] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("departure_cities", mode="before")
    @classmethod
    def normalize_departure_cities(cls, value: list[str] | None) -> list[str]:
        return _normalize_departure_cities(value)


class ClientGroupResponse(BaseModel):
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
    departure_cities: list[str] = Field(default_factory=list)
    notes: str | None = None
    deleted_at: datetime | None = None
    deleted_passport_count: int = 0
    deletion_retained_records: bool = False

    model_config = {"from_attributes": True}
