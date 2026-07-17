"""
Upload Link Presentation Schemas
================================
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=100)
    destination: str | None = Field(default=None, max_length=255)
    travel_date: date | None = None
    return_date: date | None = None
    package_name: str | None = Field(default=None, max_length=255)
    departure_cities: list[str] = Field(default_factory=list, max_length=50)
    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    meal_preference_enabled: bool = False
    require_selfie: bool = False
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("departure_cities", mode="before")
    @classmethod
    def normalize_departure_cities(cls, value: list[str] | None) -> list[str]:
        return _normalize_departure_cities(value)

    @model_validator(mode="after")
    def validate_airport_configuration(self) -> CreateClientGroupRequest:
        if self.nearest_international_airport_enabled and not self.departure_cities:
            raise ValueError("Add at least one nearest international airport when the option is enabled.")
        if not self.nearest_international_airport_enabled:
            self.departure_cities = []
        if self.travel_date and self.return_date and self.return_date < self.travel_date:
            raise ValueError("Return date cannot be before the travel date.")
        return self


class UpdateClientGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=100)
    destination: str | None = Field(default=None, max_length=255)
    travel_date: date | None = None
    return_date: date | None = None
    package_name: str | None = Field(default=None, max_length=255)
    departure_cities: list[str] = Field(default_factory=list, max_length=50)
    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    meal_preference_enabled: bool = False
    require_selfie: bool = False
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("departure_cities", mode="before")
    @classmethod
    def normalize_departure_cities(cls, value: list[str] | None) -> list[str]:
        return _normalize_departure_cities(value)

    @model_validator(mode="after")
    def validate_airport_configuration(self) -> UpdateClientGroupRequest:
        if self.nearest_international_airport_enabled and not self.departure_cities:
            raise ValueError("Add at least one nearest international airport when the option is enabled.")
        if not self.nearest_international_airport_enabled:
            self.departure_cities = []
        if self.travel_date and self.return_date and self.return_date < self.travel_date:
            raise ValueError("Return date cannot be before the travel date.")
        return self


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
    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    meal_preference_enabled: bool = False
    require_selfie: bool = False
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    notes: str | None = None
    deleted_at: datetime | None = None
    deleted_passport_count: int = 0
    deletion_retained_records: bool = False

    model_config = {"from_attributes": True}
